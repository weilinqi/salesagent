const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { createRequire } = require('node:module')

const dependencyRequire = createRequire(path.resolve(process.env.TEST_NODE_MODULES || path.join(__dirname, '../node_modules'), '../package.json'))
const ts = dependencyRequire('typescript')
const axios = dependencyRequire('axios')

function harness() {
  const effects = [], states = []
  const slots = []
  let cursor = 0
  const react = {
    createContext: () => ({ Provider: 'provider' }),
    useContext: context => context,
    useCallback: callback => callback,
    useRef: value => {
      const index = cursor++
      return slots[index] ||= { current: value }
    },
    useState: value => {
      const slot = cursor++
      const index = (slots[slot] ||= { state: states.push(value) - 1 }).state
      return [states[index], next => { states[index] = typeof next === 'function' ? next(states[index]) : next }]
    },
    useEffect: (effect, dependencies) => {
      const index = cursor++, previous = slots[index]
      if (previous && dependencies?.every((value, i) => Object.is(value, previous.dependencies[i]))) return
      const slot = slots[index] = { dependencies }
      effects.push(() => { previous?.cleanup?.(); slot.cleanup = effect(); return slot.cleanup })
    },
  }
  const cache = new Map()
  const client = axios.create()
  client.isAxiosError = axios.isAxiosError
  const load = file => {
    file = path.resolve(__dirname, '../src', file)
    if (!path.extname(file)) file += fs.existsSync(file + '.ts') ? '.ts' : '.tsx'
    if (cache.has(file)) return cache.get(file).exports
    const module = { exports: {} }; cache.set(file, module)
    const source = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: {
      module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true, target: ts.ScriptTarget.ES2020,
    } }).outputText
    const customRequire = name => {
      if (name === 'axios') return client
      if (name === 'react') return react
      if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) }
      if (name.startsWith('.')) return load(path.resolve(path.dirname(file), name))
      return dependencyRequire(name)
    }
    vm.runInThisContext(`(function(require,module,exports){${source}\n})`, { filename: file })(customRequire, module, module.exports)
    return module.exports
  }
  return { load, client, states, render: callback => { cursor = 0; return callback() }, mount: () => effects.splice(0).map(effect => effect()).filter(Boolean) }
}

function storage(initial) {
  const data = new Map(initial ? [['sales_agent_auth', JSON.stringify(initial)]] : [])
  global.localStorage = { getItem: key => data.get(key) || null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) }
}

const user = { id: 'u1', email: 'one@test.invalid', username: 'one', role: 'user', is_active: true }
const tokens = { access_token: 'new-access', refresh_token: 'new-refresh', token_type: 'bearer', expires_in: 1800, user }
const reply = (config, data, status = 200) => ({ config, data, status, statusText: '', headers: {} })
function reject(config, status) { throw new axios.AxiosError('request failed', undefined, config, undefined, reply(config, {}, status)) }
const settle = async () => { for (let i = 0; i < 30; i++) await Promise.resolve() }
module.exports = { harness, storage, user, tokens, reply, reject, settle }
