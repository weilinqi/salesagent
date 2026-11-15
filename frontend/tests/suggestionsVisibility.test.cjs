const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const ts = require('typescript')
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/components/business/practice/CustomerPreparation.tsx'), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText
function render(expanded) {
  const exports = {}
  let state = 0
  const Suggestions = () => null
  const requireMock = name => {
    if (name === 'react') return { useState: initial => [state++ === 8 ? expanded : (typeof initial === "function" ? initial() : initial), () => {}], useRef: initial => ({current:initial}), useEffect: () => {} }
    if (name === 'react/jsx-runtime') return { jsx: (type, props) => ({type,props}), jsxs: (type,props) => ({type,props}), Fragment: 'fragment' }
    if (name === './SalesSuggestions') return { default: Suggestions }
    return { default: {} }
  }
  new Function('require', 'exports', code)(requireMock, exports)
  const tree = exports.default({initialProfile:{product:"数学课",target:"家长"},onStart:()=>{},starting:false})
  const nodes=[]
  function visit(node) { if (!node || typeof node !== 'object') return; if(Array.isArray(node)) return node.forEach(visit); nodes.push(node); visit(node.props?.children) }
  visit(tree)
  return {nodes,Suggestions}
}
test('materials toggle precedes independent suggestions and defaults to collapsed', () => {
  const before=render(false)
  assert.equal(before.nodes.filter(n=>n.type===before.Suggestions).length,1)
  const panel=before.nodes.find(n=>n.props?.id==='sales-materials')
  assert.equal(panel.props.hidden,true)
  assert.ok(before.nodes.findIndex(n=>n.props?.['aria-controls']==='sales-materials') < before.nodes.findIndex(n=>n.type===before.Suggestions))
  const after=render(true)
  assert.equal(after.nodes.find(n=>n.props?.id==='sales-materials').props.hidden,false)
  assert.equal(after.nodes.filter(n=>n.type===after.Suggestions).length,1)
})
