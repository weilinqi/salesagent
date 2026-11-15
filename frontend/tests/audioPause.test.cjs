const test=require('node:test')
const assert=require('node:assert/strict')
const ts=require('typescript')
const fs=require('node:fs')
const path=require('node:path')
const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/hooks/useAudioStream.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText
function setup() {
 const audios=[]; const contexts=[]
 class Audio { constructor(){this.currentTime=0;audios.push(this)} play(){this.onplay?.();return Promise.resolve()} pause(){this.paused=true} }
 class Context { constructor(){this.state='running';this.currentTime=0;this.resumes=0;contexts.push(this)} resume(){this.resumes++;this.state='running';return Promise.resolve()} suspend(){this.state='suspended';return Promise.resolve()} close(){this.state='closed';return Promise.resolve()} decodeAudioData(){return Promise.resolve({duration:10})} createBufferSource(){return {connect(){},start(){}}} }
 const exports={}
 new Function('require','exports','Audio','window','URL','console',code)(()=>({useState:v=>[v,()=>{}],useRef:v=>({current:v}),useCallback:f=>f}),exports,Audio,{AudioContext:Context},{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},{log(){},warn(){},error(){}})
 return {hook:exports.useAudioStream(),audios,contexts}
}
test('stored audio pauses and resumes at the same position; stop resets it',async()=>{
 const {hook,audios}=setup()
 hook.playStoredAudio('SUQzAA==')
 audios[0].currentTime=3.5
 hook.pause()
 assert.equal(audios[0].paused,true)
 hook.resume()
 assert.equal(audios.length,1)
 assert.equal(audios[0].currentTime,3.5)
 hook.stop()
 assert.equal(audios[0].currentTime,0)
})
test('incoming stream chunks do not resume manually paused audio',async()=>{
 const {hook,contexts}=setup()
 hook.playChunk(new Uint8Array(9000)); await Promise.resolve(); await Promise.resolve()
 hook.pause()
 assert.equal(contexts[0].state,'suspended')
 hook.playChunk(new Uint8Array(9000)); await Promise.resolve(); await Promise.resolve()
 assert.equal(contexts[0].resumes,0)
 hook.resume(); await Promise.resolve()
 assert.equal(contexts[0].resumes,1)
 hook.stop()
 assert.equal(contexts[0].state,'closed')
})
test('late errors from the previous replay cannot disable pause on the new replay',()=>{
 const {hook,audios}=setup()
 hook.playStoredAudio('SUQzAA==','message')
 const oldError=audios[0].onerror
 hook.playStoredAudio('SUQzAA==','message')
 oldError()
 hook.pause()
 assert.equal(audios[1].paused,true)
 hook.resume()
 audios[1].onended()
 hook.playStoredAudio('SUQzAA==','message')
 hook.pause()
 assert.equal(audios[2].paused,true)
})

test('first audio auto-plays once; later updates preserve pause and manual replay works',()=>{
 const {hook,audios}=setup()
 hook.autoPlayStoredAudio('SUQzAA==','first')
 assert.equal(audios.length,1)
 audios[0].currentTime=2
 hook.pause()
 hook.autoPlayStoredAudio('SUQzAA==','first')
 assert.equal(audios.length,1)
 assert.equal(audios[0].paused,true)
 hook.resume()
 assert.equal(audios[0].currentTime,2)
 audios[0].onended()
 hook.autoPlayStoredAudio('SUQzAA==','first')
 assert.equal(audios.length,1)
 hook.playStoredAudio('SUQzAA==','first')
 assert.equal(audios.length,2)
 hook.pause()
 assert.equal(audios[1].paused,true)
 hook.autoPlayStoredAudio('SUQzAA==','second')
 assert.equal(audios.length,3)
})
