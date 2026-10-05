// 真机自查脚本（同源外部文件 —— CSP 是 script-src 'self'，**不许写成内联脚本**）。
//
// 为什么要有这一页：iOS Safari / 微信内置浏览器 / Android Chrome 的语音与拨号行为
// 靠 Chromium 自动化测不出来（`mobile_audit` 是仿真 UA + 触屏，不是真机）。
// 以前"真机验证"意味着要装一堆工具、跑一堆命令；现在只要在这台手机上打开本页，
// 它把可客观测的部分测出来、生成一段可粘贴的报告，剩下的手动项也列清楚。
//
// 诚实边界（页面上也写了）：这页只记录**这台设备的能力与降级表现**，
// 不能替代"老人能不能自己把事办完"的观察 —— 那必须真人来点。

(function () {
  'use strict';

  var results = [];

  function row(container, label, value, cls) {
    var d = document.createElement('div');
    d.className = 'row';
    var k = document.createElement('div');
    k.className = 'k';
    k.textContent = label;
    var v = document.createElement('div');
    v.className = 'v' + (cls ? ' ' + cls : '');
    v.textContent = value;
    d.appendChild(k);
    d.appendChild(v);
    container.appendChild(d);
    results.push(label + ': ' + value);
  }

  function ua() {
    return navigator.userAgent || '';
  }

  function detectBrowser() {
    var u = ua();
    if (/MicroMessenger/i.test(u)) return '微信内置浏览器';
    if (/EdgA?\//i.test(u)) return 'Edge';
    if (/CriOS/i.test(u)) return 'iOS Chrome (CriOS)';
    if (/FxiOS/i.test(u)) return 'iOS Firefox';
    if (/iPhone|iPad|iPod/i.test(u)) return 'iOS Safari（或 iOS WebView）';
    if (/Android/i.test(u)) return 'Android Chrome（或 Android WebView）';
    if (/Chrome\//i.test(u) && !/Mobile/i.test(u)) return '桌面 Chrome（不是真机）';
    return '未识别';
  }

  function env() {
    var box = document.getElementById('env');
    box.innerHTML = '';
    var isMobile = /iPhone|iPad|iPod|Android/i.test(ua());
    row(box, '浏览器（按 UA 判断）', detectBrowser(), isMobile ? 'ok' : 'warn');
    row(box, '是否移动端 UA', isMobile ? '是' : '否（请用手机打开本页）', isMobile ? 'ok' : 'bad');
    row(box, '屏幕（CSS 像素）', window.screen.width + ' × ' + window.screen.height);
    row(box, '视口（含缩放）', window.innerWidth + ' × ' + window.innerHeight);
    row(box, '设备像素比 DPR', String(window.devicePixelRatio || 1));
    row(box, '触屏点数', String((navigator.maxTouchPoints || 0)));
    row(box, '安全上下文（HTTPS）', window.isSecureContext ? '是' : '否（语音/部分能力会被浏览器禁用）',
        window.isSecureContext ? 'ok' : 'bad');
    row(box, '可安装（PWA 入口存在）', 'manifest' in document.createElement('link') ? '按浏览器菜单确认' : '未知');
    row(box, '时区', String(Intl.DateTimeFormat().resolvedOptions().timeZone || '未知'));
    row(box, '检测时间（本地）', new Date().toLocaleString());
  }

  function speech() {
    var box = document.getElementById('speech');
    box.innerHTML = '';
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SR) {
      row(box, 'SpeechRecognition 可用', '是', 'ok');
      try {
        var r = new SR();
        row(box, '识别语言默认值', String(r.lang || '（空）'));
      } catch (e) {
        row(box, '实例化识别对象', '失败：' + e.message, 'bad');
      }
    } else {
      // 这不是"错误"，而是一个**要被降级覆盖**的常态：老年端必须给打字路径
      row(box, 'SpeechRecognition 可用', '否 → 老年端应显示"已切换成打字输入"提示条并允许打字',
          'warn');
    }
    row(box, 'mediaDevices.getUserMedia 存在', navigator.mediaDevices && navigator.mediaDevices.getUserMedia ? '是' : '否');
    if (navigator.permissions && navigator.permissions.query) {
      navigator.permissions.query({ name: 'microphone' }).then(function (s) {
        row(box, '麦克风权限状态', s.state, s.state === 'granted' ? 'ok' : 'warn');
        refreshReport();
      }).catch(function () {
        row(box, '麦克风权限状态', '该浏览器不支持查询（不等于没有麦克风）', 'warn');
        refreshReport();
      });
    } else {
      row(box, '麦克风权限状态', '该浏览器不支持 Permissions API', 'warn');
    }
  }

  function tts() {
    var box = document.getElementById('tts');
    box.innerHTML = '';
    var synth = window.speechSynthesis;
    if (!synth) {
      row(box, 'speechSynthesis 可用', '否 → 老年端应显示"不能自动念出来，字已放大"的降级条', 'warn');
      return;
    }
    row(box, 'speechSynthesis 可用', '是', 'ok');
    var zh = (synth.getVoices() || []).filter(function (v) { return /^zh/i.test(v.lang || ''); });
    row(box, '中文语音包数量', String(zh.length), zh.length ? 'ok' : 'warn');
    // 无手势试播报：能触发 onstart 说明不需要手势
    var started = false;
    try {
      var u = new SpeechSynthesisUtterance('测试');
      u.onstart = function () { started = true; };
      synth.speak(u);
      setTimeout(function () {
        row(box, '无手势直接播报', started ? '可以（不依赖用户手势）' : '未触发 onstart（可能要求用户手势）',
            started ? 'ok' : 'warn');
        refreshReport();
      }, 900);
    } catch (e) {
      row(box, '无手势直接播报', '抛错：' + e.message, 'bad');
    }
  }

  function tel() {
    var box = document.getElementById('tel');
    box.innerHTML = '';
    var isMobile = /iPhone|iPad|iPod|Android/i.test(ua());
    row(box, '移动端（tel: 才能拉起拨号盘）', isMobile ? '是' : '否', isMobile ? 'ok' : 'warn');
    row(box, '口径提醒', '网页只能打开拨号盘，**没有"已接通"状态**；不会自动拨出', 'warn');
  }

  function consumeGestureNote() {
    var box = document.getElementById('tts');
    try {
      var u = new SpeechSynthesisUtterance('测试播报，来自用户点击');
      u.onstart = function () { row(box, '用户手势后播报', '可以（点击后正常发声）', 'ok'); refreshReport(); };
      u.onerror = function (ev) { row(box, '用户手势后播报', '失败：' + (ev.error || 'unknown'), 'bad'); refreshReport(); };
      window.speechSynthesis.speak(u);
    } catch (e) {
      row(box, '用户手势后播报', '抛错：' + e.message, 'bad');
    }
  }

  function refreshReport() {
    var head = ['# 真机自查报告（把这段贴回 docs/eval/真机验证记录.md）', ''];
    document.getElementById('report').value = head.concat(results).join('\n');
  }

  function run() {
    results = [];
    env();
    speech();
    tts();
    tel();
    refreshReport();
    // 语音/权限是异步的，稍后再刷一次
    setTimeout(refreshReport, 1500);
  }

  document.getElementById('speak').addEventListener('click', consumeGestureNote);
  document.getElementById('again').addEventListener('click', run);
  document.getElementById('copy').addEventListener('click', function () {
    var t = document.getElementById('report');
    t.removeAttribute('readonly');
    t.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    t.setAttribute('readonly', 'readonly');
    if (!ok && navigator.clipboard) {
      navigator.clipboard.writeText(t.value).then(function () { alert('已复制报告'); },
        function () { alert('自动复制被拦截，请长按选择后复制'); });
      return;
    }
    alert(ok ? '已复制报告' : '自动复制被拦截，请长按选择后复制');
  });

  run();
})();
