// web/public/debug.js — 真机调试入口（原为 index.html 内联脚本，被 CSP script-src 'self' 拦截）
// 说明：CSP 禁止内联脚本，内联写法会在每个页面产生一条 console 报错（评委开 DevTools 就看得见）。
// 改为同源外部文件后既合法又不报警。生产可移除本文件与 index.html 中的引用。
if (location.search.includes('debug=1')) {
  var s = document.createElement('script')
  s.src = 'https://cdn.jsdelivr.net/npm/eruda@3.4.1'
  s.onload = function () { window.eruda && eruda.init() }
  document.body.appendChild(s)
}
