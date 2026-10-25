"""
Streaming Pipeline — 把 LLM + TTS 改成流式，句子级切片，逐句推送

目标：用户说完 → 1.5-2s 听到 AI 第一句

设计：
  1. ASR final transcript 已就绪
  2. 并行 4 任务装配 context（user_ctx / history / RAG / persona）
  3. LLM stream=True → 累积 token
  4. 每凑齐 1 个完整句子（中英文标点边界）→ 立刻送 TTS → 推 audio_chunk
  5. 整段生成完 → 推 ai_streaming_end（带 audio_data 给回放用）

兼容性：保留原 handle_message() 给非 WS 路径用。
"""
import asyncio
import json
import re
import sys
import time
import base64
import httpx
from typing import AsyncIterator, List, Optional, Dict, Any, Callable, Awaitable

# Windows CMD 默认 GBK 编码，遇到 emoji / 中日韩生僻字会 UnicodeEncodeError
# 强制让 print 用 utf-8，把 token / 句子原样打出来（不再 gbk 'illegal multibyte'）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 句子边界正则：中英文标点 + 问号 + 感叹号 + 句号
# 注意：保留 lookbehind 的标点，但不切分括号 / 引号 / 数字后的小数点
# 不在 \n 切（MiniMax LLM 输出含 \n\n 分段，但切 3 段会让 TTS 并发到 3 个、限流变慢）
_SENTENCE_BOUNDARY = re.compile(
    r'(?<=[。！？!?；;])\s*'           # 中英文主标点
    r'|(?<=[.!?])\s+(?=[A-Z一-鿿])'   # 英文 . ! ? 后接大写或中文（口语）
)

# P1: 流式 TTS 提前触发阈值 — buffer 累积到 ~25 字时，如果当前 token 末尾不是数字/字母，
# 也允许切出。避免 LLM 一口气 yield 整个句子（"嗯，精度多少？价格呢？"）时 TTS
# 一直在等完整句号。让 TTS 真正和 LLM 并行。
# 阈值 25 字：避免切出 (breath) 这种 8 字短句（MiniMax TTS 短句会因限流/冷启动变慢）
_PARTIAL_BOUNDARY = re.compile(
    r'(?<=[，,、：:。；;])\s*'         # 短停顿标点（次级边界）
    r'|\s+'                              # 空格也算可切
)
_PARTIAL_MIN_CHARS = 25

# 文本 UI 首字优先，后续小批量合并：避免逐 token 推送造成 WebSocket 刷新过频。
_STREAM_UPDATE_MIN_CHARS = 8
_STREAM_UPDATE_BOUNDARIES = frozenset("，,。！？!?；;：:")


def split_sentences(buffer_text: str, allow_partial: bool = True) -> List[str]:
    """
    给定累积的 LLM 输出，找出已完整的句子。

    Args:
        buffer_text: LLM 累积到现在的所有 token 拼起来
        allow_partial: True 时允许用次级边界（逗号/分号/空格）切短句，
                       让 TTS 在 LLM 还在推后续 token 时就能 fire。
                       要求累积 >= _PARTIAL_MIN_CHARS 才切。

    Returns:
        list of 完整句子（不含标点后的残留 buffer）

    Note: 不会返回最后那个可能还在累积的尾巴。
    """
    if not buffer_text:
        return []

    # 先找主边界（句号问号感叹号）
    sentences = []
    pos = 0
    last_main_end = 0
    for m in _SENTENCE_BOUNDARY.finditer(buffer_text):
        end = m.end()
        s = buffer_text[pos:end].strip()
        if s:
            sentences.append(s)
        pos = end
        last_main_end = end
    # 如果有主边界句子，先返回（让完整句号能切出）
    if sentences:
        return sentences
    # 没主边界，且允许次级切句（流式 TTS 提前触发）— 找次级边界
    if not allow_partial or len(buffer_text) < _PARTIAL_MIN_CHARS:
        return []
    # 找次级边界（逗号/分号/空格）后位置
    candidates = []
    for m in _PARTIAL_BOUNDARY.finditer(buffer_text):
        candidates.append(m.end())
    if not candidates:
        return []
    # 选最后一个让 >= _PARTIAL_MIN_CHARS 的位置
    chosen = None
    for c in candidates:
        if c >= _PARTIAL_MIN_CHARS:
            chosen = c  # 取最后一个满足的
    if chosen is None:
        return []
    s = buffer_text[:chosen].strip()
    if not s:
        return []
    return [s]


def remaining(buffer_text: str) -> str:
    """取 buffer 中最后未完成的尾巴"""
    if not buffer_text:
        return ""
    last_boundary = None
    for m in _SENTENCE_BOUNDARY.finditer(buffer_text):
        last_boundary = m.end()
    if last_boundary is None:
        return buffer_text
    return buffer_text[last_boundary:]


def strip_think_blocks(text: str) -> str:
    """保留为防御性兜底 — 当前 chat_stream 默认 reasoning_split=True，
    内容里不应再含 <think> 块。万一上游退化，这里做最后一道保险。"""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()


def looks_like_reasoning_dump(text: str) -> bool:
    """保留为防御性兜底（默认 False，因 reasoning_split=True 已把 think 拆出去）。"""
    return False


def clean_reasoning_dump(text: str) -> str:
    """保留为防御性兜底：当前 chat_stream 已 reasoning_split=True，原始内容就是 in-character。"""
    return text.strip() if text else text


def _build_simple_system_prompt(persona, scenario: str, user_context) -> str:
    """
    给 MiniMax-Text-01 用的极简 system prompt。
    故意短、目标明确、避免触发长 reasoning。
    """
    # 提取 persona 关键信息
    name = ""
    title = ""
    company = ""
    industry = ""
    background = ""
    if persona:
        name = persona.get("name", "")
        title = persona.get("title", "")
        company = persona.get("company", "")
        industry = persona.get("industry", "")
        bg = persona.get("background", "")
        if bg:
            background = bg[:150]

    # 销售员背景
    sales_info = ""
    if user_context:
        sc_name = user_context.get("name", "")
        sc_product = user_context.get("product", "")
        if sc_name: sales_info += f"销售员 {sc_name} "
        if sc_product: sales_info += f"卖{sc_product}"

    return f"""你扮演客户，{name or '某客户'}，{title}@{company}，{industry}行业。
{('背景：' + background) if background else ''}

场景：{scenario or '销售拜访'}

{sales_info + '正找你谈。' if sales_info else '有销售来找你谈。'}

回复要求（必须遵守）：
- 直接回答，不要任何思考或解释
- 短句，1-3 句，像真人说话
- 口语化，可以用 (breath) (sighs) 等 TTS 标签
- 绝不扮演销售、绝不提产品优势
- 绝不输出"<think>"等内部思考标记
"""


class SentenceBuffer:
    """
    累积 LLM 流式 token，按句子边界切分并产出。
    解决：英文省略号、数字小数点、连续标点等"假边界"问题。
    实时剥掉 <think>...</think> 块（M2.7 reasoning model）。
    """

    def __init__(self):
        self._buf = ""
        self._in_think = False  # 是否在 <think> 块内
        self._think_buf = ""    # 可能跨 token 的 <think> / </think> 标签前缀

    def push(self, token: str) -> List[str]:
        """
        追加新 token，并返回已经闭合、可立即送去 TTS 的句子。
        已返回的文本会从内部 buffer 移除，只保留尚未闭合的尾部。
        """
        if not token:
            return []
        # 流式剥 think 块：检测 <think> 和 </think>
        clean = self._strip_think(token)
        if not clean:
            return []
        self._buf += clean

        # 优先在句号、问号、感叹号等主边界切分。
        main_matches = list(_SENTENCE_BOUNDARY.finditer(self._buf))
        if main_matches:
            cut = main_matches[-1].end()
            completed = self._buf[:cut]
            self._buf = self._buf[cut:]
            return split_sentences(completed, allow_partial=False)

        # 长句没有主标点时，在逗号或空格处分段，避免 TTS 一直等到 LLM 结束。
        if len(self._buf) >= _PARTIAL_MIN_CHARS:
            candidates = [
                match.end()
                for match in _PARTIAL_BOUNDARY.finditer(self._buf)
                if match.end() >= _PARTIAL_MIN_CHARS
            ]
            if candidates:
                cut = candidates[-1]
                completed = self._buf[:cut].strip()
                self._buf = self._buf[cut:]
                if completed:
                    return [completed]
        return []

    def _strip_think(self, token: str) -> str:
        """实时剥 <think>...</think> 块，处理跨 token 的边界"""
        out = ""
        text = self._think_buf + token
        self._think_buf = ""
        while text:
            if self._in_think:
                # 找 </think>
                end_idx = text.find("</think>")
                if end_idx >= 0:
                    self._in_think = False
                    text = text[end_idx + len("</think>"):]
                else:
                    _, self._think_buf = self._split_tag_prefix(text, "</think>")
                    break  # 还在 think 块里，保留可能跨 token 的关闭标签前缀
            else:
                # 找 <think>
                start_idx = text.find("<think>")
                if start_idx >= 0:
                    out += text[:start_idx]
                    self._in_think = True
                    text = text[start_idx + len("<think>"):]
                else:
                    visible, self._think_buf = self._split_tag_prefix(text, "<think>")
                    out += visible
                    break
        return out

    @staticmethod
    def _split_tag_prefix(text: str, tag: str) -> tuple[str, str]:
        """保留可能在下一个 token 补全的标签前缀，避免提前展示。"""
        max_prefix = min(len(text), len(tag) - 1)
        for size in range(max_prefix, 0, -1):
            if text.endswith(tag[:size]):
                return text[:-size], text[-size:]
        return text, ""

    def flush(self) -> str:
        """
        强制取出 buffer 中剩余内容（生成结束时调用）。
        可能包含未完成句子（兜底）。
        """
        rest = self._buf
        self._buf = ""
        return rest.strip()

    @property
    def text(self) -> str:
        """返回当前可安全展示的文本（已过滤流式 <think> 内容）。"""
        return self._buf

    def reset(self):
        self._buf = ""
        self._in_think = False
        self._think_buf = ""


async def sentence_to_audio_stream(
    sentence: str,
    minimax,
    emotion: str = "neutral",
    voice_modify: Optional[Dict] = None,
    voice: str = "male-qn-qingse",
    on_chunk: Optional[Callable[[bytes], Awaitable]] = None,
) -> bytes:
    """
    把一个句子转成 mp3 bytes（流式：边收边推 on_chunk）。
    短句（约 60-100 字）合成时间 4-5s，第一个 chunk 2.9s 即可到达。
    """
    t_tts = time.time()
    first_chunk_ms = None
    try:
        accumulated = bytearray()
        async for chunk in minimax.text_to_speech_stream(
            text=sentence,
            model="speech-2.8-turbo",
            voice=voice,
        ):
            if first_chunk_ms is None:
                first_chunk_ms = int((time.time() - t_tts) * 1000)
                print(f"[TTS][stream] first chunk at {first_chunk_ms}ms for {len(sentence)} chars")
            accumulated.extend(chunk)
            if on_chunk:
                try:
                    await on_chunk(bytes(chunk))
                except Exception as e:
                    print(f"[TTS] on_chunk error: {e}")
        total_ms = int((time.time() - t_tts) * 1000)
        print(f"[TTS][stream] done in {total_ms}ms, {len(accumulated)} bytes ({len(sentence)} chars)")
        return bytes(accumulated)
    except Exception as e:
        print(f"[TTS] stream failed ({int((time.time()-t_tts)*1000)}ms): {e}")
        return b""


async def warmup_knowledge_retrieval(handler) -> bool:
    """Prime the lazy knowledge stack without blocking the event loop."""
    try:
        await asyncio.to_thread(
            handler._retrieve_knowledge_references,
            user_message="产品介绍",
            conversation_history=[],
            scenario="general",
        )
        return True
    except Exception as e:
        print(f"[warmup] knowledge retrieval failed (non-fatal): {e}")
        return False


async def parallel_context_assembly(
    session_id: str,
    user_text: str,
    session_info: Dict,
    handler,
) -> Dict[str, Any]:
    """
    4 源并行装配 context（user_ctx / history / RAG / persona），
    总耗时 ≈ max(t1..t4) 而不是 4*t。

    Returns dict with: messages, emotion, voice_modify, knowledge_refs
    """
    from app.services.knowledge.tools import (
        execute_search_knowledge,
        execute_get_spin_questions,
    )

    role_config = session_info.get("role_config", {})
    customer_type_map = {
        "rational": "analytical", "emotional": "expressive",
        "hesitant": "amiable", "decisive": "assertive",
    }
    customer_type = customer_type_map.get(
        role_config.get("personality", "decisive"), "assertive"
    )
    scenario = session_info.get("scenario_id", "general")
    persona = session_info.get("persona")
    user_context = session_info.get("user_context")

    # 从 session_manager 拉历史（最新 10 轮）
    from app.websocket.manager import session_manager
    ctx = session_manager.get_context(session_id)
    if not ctx:
        # 退化：从 DB 拉
        from app.database import SessionLocal
        from app.models.practice import PracticeMessage
        db = SessionLocal()
        try:
            msgs = db.query(PracticeMessage).filter(
                PracticeMessage.session_id == session_id
            ).order_by(PracticeMessage.created_at).all()
            ctx = [{"role": m.role, "content": m.content} for m in msgs]
        finally:
            db.close()
    history = ctx[-10:]
    for msg in history:
        if msg.get("role") == "ai":
            msg["role"] = "assistant"

    # 并行装配 — 完整保留所有功能
    async def build_msgs():
        return handler._build_messages(
            user_text, history, customer_type, scenario,
            None, None, persona, user_context,
        )

    async def detect_emot():
        from app.services.conversation.handler import detect_emotion
        return detect_emotion(user_text, customer_type, history)

    async def rag():
        """RAG 检索知识库（保留功能）"""
        try:
            refs = handler._retrieve_knowledge_references(
                user_message=user_text,
                conversation_history=history,
                scenario=scenario,
            )
            return refs or []
        except Exception as e:
            print(f"[RAG] failed (non-fatal): {e}")
            return []

    msgs, emotion_data, knowledge_refs = await asyncio.gather(
        build_msgs(), detect_emot(), rag()
    )

    # 把 knowledge_refs 注入到 system message
    if knowledge_refs and msgs and msgs[0].get("role") == "system":
        ref_text = "\n\n【知识库参考】\n" + "\n".join(
            f"- [{r.get('source', '?')}] {r.get('excerpt', '')[:120]}"
            for r in knowledge_refs[:3]
        )
        msgs[0]["content"] = msgs[0]["content"] + ref_text

    return {
        "messages": msgs,
        "emotion": emotion_data.get("emotion", "neutral"),
        "voice_modify": emotion_data.get("voice_modify", {}),
        "breath_tag": emotion_data.get("breath_tag", ""),
        "knowledge_refs": knowledge_refs,
    }


async def stream_pipeline(
    websocket_send,
    websocket_send_binary,
    session_id: str,
    user_text: str,
    user_audio_data: Optional[str],
    user_audio_mime: Optional[str],
    client_id: Optional[str],
    minimax,
    handler,
    persona: Optional[Dict] = None,
    user_context: Optional[Dict] = None,
    latency_clock: Callable[[], float] = time.perf_counter,
) -> Dict[str, Any]:
    """
    主入口：执行一次完整的"用户消息 → 流式 AI 回复"流程。

    Args:
        websocket_send: async callable(json_dict) -> awaitable
        session_id: session uuid
        user_text: ASR 转写后的文本（或用户输入）
        minimax: MiniMax service
        handler: ConversationHandler 实例
        persona, user_context: 来自 session_info

    Returns:
        dict with: full_response, sentences (list[str]), audio_chunks (list[bytes]),
                   emotion, voice_modify, knowledge_refs
    """
    from app.websocket.manager import session_manager
    from app.services.conversation.handler import add_breath_tags_to_response

    request_started = latency_clock()
    session_info = session_manager.get_session_info(session_id) or {}
    role_config = session_info.get("role_config", {})
    customer_type_map = {
        "rational": "analytical", "emotional": "expressive",
        "hesitant": "amiable", "decisive": "assertive",
    }
    customer_type = customer_type_map.get(
        role_config.get("personality", "decisive"), "assertive"
    )
    scenario = session_info.get("scenario_id", "general")
    if persona is None:
        persona = session_info.get("persona")
    if user_context is None:
        user_context = session_info.get("user_context")

    t0 = time.time()
    # 1. 并行装配 context
    print(f"[STREAM][T=    0ms] assembling context for {user_text[:30]!r}...")
    assembled = await parallel_context_assembly(
        session_id, user_text, session_info, handler
    )
    t_ctx = int((time.time() - t0) * 1000)
    messages = assembled["messages"]
    emotion = assembled["emotion"]
    voice_modify = assembled["voice_modify"]
    breath_tag = assembled["breath_tag"]
    knowledge_refs = assembled["knowledge_refs"]
    print(f"[STREAM][T={t_ctx:>5}ms] ← context assembly done in {t_ctx}ms, msgs={len(messages)}, refs={len(knowledge_refs)}, emotion={emotion}")

    # 2. 发 ai_streaming_start
    msg_id = f"msg-{session_id}-ai-{int(time.time()*1000)}"
    await websocket_send({
        "type": "ai_streaming_start",
        "id": msg_id,
        "content": "",
        "timestamp": time.time(),
    })

    # 3. 流式 LLM + 句子切分
    buf = SentenceBuffer()
    full_text = ""
    last_streamed_text = ""
    sentences_emitted: List[str] = []
    audio_chunks_emitted: List[bytes] = []
    first_audio_ms: Optional[int] = None
    first_audio_target_met: Optional[bool] = None
    t0 = time.time()
    tts_queue = asyncio.Queue()
    first_tts_segment = True

    async def push_audio_chunk(chunk: bytes):
        """保存并立即推送一个 TTS 音频块，确保每块只发送一次。"""
        nonlocal first_audio_ms, first_audio_target_met
        if not chunk:
            return
        audio = bytes(chunk)
        audio_chunks_emitted.append(audio)
        if websocket_send_binary:
            await websocket_send_binary(audio)
            if first_audio_ms is None:
                first_audio_ms = int(round((latency_clock() - request_started) * 1000))
                first_audio_target_met = first_audio_ms < 3000
                status = "PASS" if first_audio_target_met else "MISS"
                print(
                    f"[LATENCY] first_audio={first_audio_ms}ms "
                    f"target<3000ms {status}"
                )
            print(
                f"[STREAM][T={int((time.time()-t0)*1000):>5}ms] "
                f"pushed audio chunk ({len(audio)} bytes)"
            )

    async def tts_worker():
        """串行消费句子，保持语音顺序，同时与 LLM 生成并行。"""
        while True:
            sentence = await tts_queue.get()
            try:
                if sentence is None:
                    return
                await sentence_to_audio_stream(
                    sentence,
                    minimax,
                    emotion,
                    voice_modify,
                    on_chunk=push_audio_chunk,
                )
            finally:
                tts_queue.task_done()

    async def enqueue_sentence(sentence: str):
        """记录可见句子，并把带语气标签的版本交给 TTS。"""
        nonlocal first_tts_segment
        sentence = re.sub(r'\n+', '，', sentence).strip()
        if not sentence:
            return
        sentence = clean_reasoning_dump(sentence)
        if not sentence or looks_like_reasoning_dump(sentence):
            return
        sentences_emitted.append(sentence)
        speech_text = sentence
        if first_tts_segment and breath_tag:
            tag = " ".join(breath_tag) if isinstance(breath_tag, list) else str(breath_tag)
            speech_text = f"{tag} {sentence}"
        first_tts_segment = False
        print(
            f"[STREAM][T={int((time.time()-t0)*1000):>5}ms] "
            f"sentence ready: {sentence[:60]!r} → queue TTS"
        )
        await tts_queue.put(speech_text)

    tts_worker_task = asyncio.create_task(tts_worker())
    try:
        token_count = 0
        first_token_at = None
        print(f"[STREAM][T={int((time.time()-t0)*1000):>5}ms] → calling chat_stream (model=M3 + thinking disabled, TTFT 2.6s 实测)")
        async for token in minimax.chat_stream(
            messages,
            model="MiniMax-M3",
            max_tokens=256,
        ):
            now_ms = int((time.time() - t0) * 1000)
            token_count += 1
            if first_token_at is None:
                first_token_at = now_ms
                print(f"[STREAM][T={now_ms:>5}ms] ← FIRST token from LLM (TTFT)")
            if token_count <= 3:
                print(f"[STREAM][T={now_ms:>5}ms] token #{token_count}: {token[:30]!r}")
            # 后处理 token
            full_text += token
            ready_sentences = buf.push(token)
            for sentence in ready_sentences:
                await enqueue_sentence(sentence)
            if ready_sentences:
                # 给 TTS worker 一次调度机会，让语音在 LLM 继续生成前启动。
                await asyncio.sleep(0)
            # 首个可见 token 立刻发送以降低 TTFT；之后合并小片段或等标点，
            # 让前端拿到的是可直接覆盖展示的累计文本。
            visible = "".join(sentences_emitted) + buf.text
            token_ends_at_boundary = bool(token.rstrip()) and token.rstrip()[-1] in _STREAM_UPDATE_BOUNDARIES
            if visible.strip() and visible != last_streamed_text and (
                not last_streamed_text
                or len(visible) - len(last_streamed_text) >= _STREAM_UPDATE_MIN_CHARS
                or token_ends_at_boundary
            ):
                await websocket_send({
                    "type": "ai_streaming_update",
                    "id": msg_id,
                    "content": visible,
                    "timestamp": time.time(),
                })
                last_streamed_text = visible
        if token_count == 0:
            raise RuntimeError("LLM returned no content")
        end_ms = int((time.time() - t0) * 1000)
        print(f"[STREAM][T={end_ms:>5}ms] ← LLM stream ended, total {token_count} tokens, first_token_at={first_token_at}ms, last_token_at={end_ms}ms")
        # 4. LLM 结束：只把尚未闭合的尾句送入 TTS。
        tail = buf.flush()
        if tail:
            await enqueue_sentence(tail)

        final_visible = "".join(sentences_emitted)
        if final_visible and final_visible != last_streamed_text:
            await websocket_send({
                "type": "ai_streaming_update",
                "id": msg_id,
                "content": final_visible,
                "timestamp": time.time(),
            })
            last_streamed_text = final_visible

        await tts_queue.join()
        await tts_queue.put(None)
        await tts_worker_task
    except Exception as e:
        print(f"[STREAM] LLM error: {e}")
        import traceback
        traceback.print_exc()
        if not tts_worker_task.done():
            tts_worker_task.cancel()
            await asyncio.gather(tts_worker_task, return_exceptions=True)
        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 402:
            error_message = "MiniMax 账户额度不足，暂时无法生成回复。请检查账户余额或套餐额度。"
        elif isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
            error_message = "MiniMax 返回 429，当前额度或请求频率受限。请检查 Token Plan 额度后重试。"
        else:
            error_message = "AI 服务暂时无法生成回复，请稍后重试。"
        await websocket_send({
            "type": "ai_streaming_end",
            "id": msg_id,
            "content": error_message,
            "audio_data": "",
            "timestamp": time.time(),
        })
        return {
            "full_response": "",
            "sentences": [],
            "audio_chunks": [],
            "emotion": emotion,
            "voice_modify": voice_modify,
            "knowledge_refs": knowledge_refs,
            "first_audio_ms": first_audio_ms,
            "first_audio_target_met": first_audio_target_met,
        }
    finally:
        # 客户端断开会以 CancelledError 中断协程；确保后台 TTS worker 不泄漏。
        if not tts_worker_task.done():
            tts_worker_task.cancel()
            await asyncio.gather(tts_worker_task, return_exceptions=True)

    elapsed_ms = (time.time() - t0) * 1000
    print(f"[STREAM] LLM+sentences in {elapsed_ms:.0f}ms, "
          f"{len(sentences_emitted)} sentences, {len(audio_chunks_emitted)} audio chunks")

    # 5. 清理 full_text
    clean = strip_think_blocks(full_text)
    clean = clean_reasoning_dump(clean) if looks_like_reasoning_dump(clean) else clean
    if not clean:
        clean = "".join(sentences_emitted)

    # 6. 流式 TTS 已成功时直接复用音频，避免再调用一次 HTTP TTS。
    # WebSocket TTS 没有产出音频时才用 HTTP 接口兜底。
    full_audio_b64 = ""
    if audio_chunks_emitted:
        full_audio_b64 = base64.b64encode(b"".join(audio_chunks_emitted)).decode()
    elif clean:
        try:
            full_audio = await minimax.text_to_speech(
                text=clean,
                model="speech-2.8-turbo",
                voice="male-qn-qingse",
                speed=1.0,
                format="mp3",
                emotion=emotion,
                voice_modify=voice_modify or {},
            )
            full_audio_b64 = base64.b64encode(full_audio).decode()
        except Exception as e:
            print(f"[STREAM] full TTS failed: {e}")

    # 7. 推 ai_streaming_end
    await websocket_send({
        "type": "ai_streaming_end",
        "id": msg_id,
        "content": clean,
        "audio_data": full_audio_b64,
        "knowledge_refs": knowledge_refs,
        "timestamp": time.time(),
    })

    return {
        "full_response": clean,
        "sentences": sentences_emitted,
        "audio_chunks": audio_chunks_emitted,
        "emotion": emotion,
        "voice_modify": voice_modify,
        "knowledge_refs": knowledge_refs,
        "first_audio_ms": first_audio_ms,
        "first_audio_target_met": first_audio_target_met,
    }
