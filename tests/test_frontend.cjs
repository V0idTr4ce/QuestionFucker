// 浏览器逻辑模拟：仅检查离线搜索，不启动 AI 服务。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'QuestionFucker.html'), 'utf8');
const match = html.match(/<script>\s*([\s\S]*?)\s*<\/script>/);
assert.ok(match, '找不到页面内联脚本');
const elements = {};
function element(id) {
    return elements[id] ||= {value: '', innerHTML: '', textContent: '', className: '',
        classList: {add(){}, remove(){}}, addEventListener(){}, focus(){}, select(){}};
}
const requests = [];
const context = {window: {}, location: {search: ''}, URLSearchParams,
    document: {getElementById: element, addEventListener(){}, activeElement: null},
    fetch(url) { requests.push(url); return new Promise(() => {}); },
    setTimeout(){}, clearTimeout(){}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root, 'data/questions.js'), 'utf8'), context);
vm.runInContext(match[1], context);
for (const query of ['最小权限原则的含义是？A.无限授权B.只授予必要权限',
                     '最小权限原则的含义是？\nA.无限授权\nB.只授予必要权限']) {
    element('search').value = query;
    vm.runInContext('render()', context);
    assert.match(element('results').innerHTML, /最小权限原则的含义是/);
}
element('search').value = '3389';
vm.runInContext('render()', context);
assert.match(element('results').innerHTML, /3389/);
element('search').value = '远程桌面协议 RDP 的默认端口号是？A.22B.3389C.5900D.8080';
vm.runInContext('render()', context);
assert.match(element('results').innerHTML.replace(/<[^>]*>/g, ''), /远程桌面协议RDP默认使用的端口/);
assert.match(element('hint').textContent, /相似题/);
assert.ok(requests.every(url => !url.includes('/api/ask')), '输入不应触发 AI');
console.log('前端纯文本搜索、粘贴整题与不自动调用 AI：通过');
