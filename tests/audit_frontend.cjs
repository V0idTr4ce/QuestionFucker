// node tests/audit_frontend.cjs <test-records.jsonl>
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const rows = fs.readFileSync(process.argv[2], 'utf8').replace(/^\uFEFF/, '').trim().split(/\r?\n/).map(JSON.parse);
const html = fs.readFileSync(path.join(root, 'QuestionFucker.html'), 'utf8');
const script = html.match(/<script>\s*([\s\S]*?)\s*<\/script>/)[1];
const elements = {};
const element = id => elements[id] ||= {value: '', innerHTML: '', textContent: '', className: '',
    classList: {add(){}, remove(){}}, addEventListener(){}, focus(){}, select(){}};
const context = {window: {}, location: {search: ''}, URLSearchParams,
    document: {getElementById: element, addEventListener(){}, activeElement: null},
    fetch() { return new Promise(() => {}); }, setTimeout(){}, clearTimeout(){}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root, 'data/questions.js'), 'utf8'), context);
vm.runInContext(script, context);
const formats = {
    stem_only: r => r.stem,
    multiline: r => r.stem + '\n' + Object.entries(r.options).map(([k, v]) => `${k}. ${v}`).join('\n'),
    compact: r => r.stem + Object.entries(r.options).map(([k, v]) => `${k}.${v}`).join(''),
};
const counts = Object.fromEntries(Object.keys(formats).map(name => [name, {some_result: 0, none: 0}]));
for (const r of rows) for (const [name, makeText] of Object.entries(formats)) {
    element('search').value = makeText(r);
    vm.runInContext('render()', context);
    counts[name][element('results').innerHTML.includes('<article class="q">') ? 'some_result' : 'none']++;
}
console.log(JSON.stringify({count: rows.length, summary: counts}, null, 2));
