/* 前端主脚本
 * ==========
 *  1. 启动时检测后端连接状态（导航栏小圆点 + 文字）
 *  2. SSE 自动重连（最多 3 次，间隔 1.5s）
 *  3. 输入框 Enter 发送 / Shift+Enter 换行 / 高度自适应
 *  4. XSS 强化：所有 user 输入走 textContent，Markdown 渲染后再 escape
 *  5. 移动端响应式
 *  6. 静默 @vite/client 404（浏览器扩展噪音）
 */

/* 工具函数
 * ======== */
const $ = (id) => document.getElementById(id);

/* 回到底部
 * ========
   长对话往回翻查历史时，想回最新消息原来只能一直往下拖。
   离底部超过 200px 才显示按钮，贴着底时不打扰。 */
function scrollToBottom() {
  const wrap = $("messages");
  if (wrap) wrap.scrollTo({ top: wrap.scrollHeight, behavior: "smooth" });
}
function initScrollWatcher() {
  const wrap = $("messages");
  const btn = $("scrollBottomBtn");
  if (!wrap || !btn) return;
  const update = () => {
    const far = wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight > 200;
    btn.classList.toggle("show", far);
  };
  /* passive:true 告诉浏览器这个监听不会 preventDefault，滚动不会被阻塞 */
  wrap.addEventListener("scroll", update, { passive: true });
  update();
}

/* 自动检测版本：老版本自动 reload 拿新 HTML
 * ========================================= */
const CURRENT_VERSION = "v2.0-20261020a";
(function autoReloadOnVersionMismatch() {
  const SAVED_VERSION_KEY = "platform_html_version";
  const last = localStorage.getItem(SAVED_VERSION_KEY);
  if (last && last !== CURRENT_VERSION) {
    /* 老版本 → 记录新版本 + 强刷拿新 HTML（带 cache buster 绕过所有缓存层） */
    localStorage.setItem(SAVED_VERSION_KEY, CURRENT_VERSION);
    const url = location.pathname + "?v=" + Date.now();
    location.replace(url);  // 浏览器历史不留痕
    return;
  }
  localStorage.setItem(SAVED_VERSION_KEY, CURRENT_VERSION);
})();

/* 转义 HTML（防 XSS，所有用户输入必须先过这个） */
function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/* fetch 手写 SSE（替代 EventSource）
 * ==================================
   EventSource 只能 GET、不能自定义请求头（JWT 只能塞 query param）。
   改用 fetch POST：ReadableStream 按 SSE 协议自行切帧——以空行分隔，
   每条以 "data:" 开头。onMessage 收到已解析的帧对象。
   返回 {close}：AbortController 主动断开（「停止生成」用）。
   注意：正常读完(读到 done:true)不触发 onError；只有网络错/HTTP 非 2xx 才触发。 */
function openSSE(url, body, onMessage, onError, onComplete) {
  const controller = new AbortController();
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  let aborted = false;

  /* 【关键】本函数必须【同步】return handle，不能是 async：
     调用方写的是 `stream = openSSE(...)` 然后 `stream.close()`。
     一旦标成 async，返回值就变成 Promise（.then 里才是 handle），
     `stream.close()` 就成了 Promise.close() → TypeError，cleanup 在复位发送态之前就抛错，
     表现为「答完后按钮停在停止、必须手动点结束」。所以这里同步返回 handle，
     真正的异步读取用一个不 await 的 IIFE 跑。 */
  (async () => {
    try {
      const resp = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!resp.ok || !resp.body) { onError(new Error("HTTP " + resp.status)); return; }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        /* SSE 帧以空行（\n\n）分隔；切出后逐条取 data: 行 */
        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const raw = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const dataLine = raw.split("\n").find((l) => l.startsWith("data:"));
          if (!dataLine) continue;
          let frame;
          try { frame = JSON.parse(dataLine.slice(5).trim()); } catch { continue; }
          /* 单帧处理抛错不能冒泡到 fetch 循环——否则 while(reader.read()) 被异常打断，
             后续帧全部收不到，表现为「后端答完了、前端空白且无报错」。捕获后降级提示。 */
          try {
            onMessage(frame);
          } catch (e) {
            console.error("[SSE] 帧处理异常：", e, frame);
          }
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") onError(e);
      return;
    }
    /* 流自然结束（reader EOF）：兜底复位发送态。即便最后一个 done 帧因缓冲/切分没被
       onMessage 处理到，连接关闭后也必须解锁输入。主动 abort 时不触发。 */
    if (!aborted && typeof onComplete === "function") onComplete();
  })();

  return {
    close: () => { aborted = true; controller.abort(); },
  };
}

/* Toast 提示 */
function toast(msg, type = "info", duration = 3000) {
  const icons = { success: "✓", error: "✕", warn: "⚠", info: "ℹ" };
  const container = $("toastContainer");
  const t = document.createElement("div");
  t.className = "toast " + type;
  t.innerHTML = `<span class="toast-icon">${icons[type] || icons.info}</span><span>${escapeHtml(msg)}</span>`;
  container.appendChild(t);
  setTimeout(() => {
    t.classList.add("fade-out");
    setTimeout(() => t.remove(), 300);
  }, duration);
}

/* 静默浏览器扩展噪音（@vite/client / openapi.json 心跳 abort）
 * ============================================================ */
(function () {
  const origError = console.error;
  console.error = function (...args) {
    const msg = args.map(a => (a && a.toString) ? a.toString() : String(a)).join(" ");
    if (msg.includes("@vite/client") || msg.includes("/@vite/")) return;
    if (msg.includes("ERR_ABORTED") && msg.includes("openapi.json")) return;
    origError.apply(console, args);
  };
})();

/* 连接状态检测
 * ============ */
let healthCheckTimer = null;
let healthCheckAbort = null;  // 用于打断上一次未完成的 HEAD 请求
async function checkHealth() {
  const dot = $("connDot");
  const txt = $("connText");
  /* 打断上一次未完成的请求，避免 ERR_ABORTED 噪声 */
  if (healthCheckAbort) healthCheckAbort.abort();
  healthCheckAbort = new AbortController();
  try {
    const r = await fetch("/openapi.json", { method: "HEAD", cache: "no-store", signal: healthCheckAbort.signal });
    if (r.ok) {
      dot.className = "conn-dot ok";
      txt.textContent = "服务正常";
    } else {
      dot.className = "conn-dot warn";
      txt.textContent = `服务异常 (${r.status})`;
    }
  } catch (e) {
    /* abort 触发的 AbortError 是预期的（页面切走时正常取消），不显示错误 */
    if (e.name === "AbortError") return;
    dot.className = "conn-dot err";
    txt.textContent = "服务离线";
  }
}
function startHealthCheck() {
  checkHealth();
  healthCheckTimer = setInterval(checkHealth, 60000); // 60s 心跳
}

/* Markdown 渲染（先 escape 再翻译）
 * ================================= */
function renderMd(s) {
  if (s == null) return "";
  let t = escapeHtml(s);
  t = t.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  t = t.replace(/^#{1,6}\s*(.+)$/gm, "<b>$1</b>");
  t = t.replace(/^[\-\*]\s+(.+)$/gm, "&bull;&nbsp;$1");
  t = t.replace(/^&gt;\s?(.+)$/gm, '<blockquote class="md-quote">$1</blockquote>');
  /* 表格：| col1 | col2 | 行 */
  t = t.replace(/((?:^\|.+\|\s*\n)+)/gm, function (block) {
    const rows = block.trim().split("\n").filter((r) => r.includes("|"));
    if (rows.length < 2) return block;
    let html = '<table style="border-collapse:collapse;margin:8px 0;font-size:13px;width:100%">';
    rows.forEach((r, i) => {
      /* 过滤掉首尾空字符串（Markdown 表格首尾 | 会有空），再识别分隔行（---/:::） */
      const real = r.split("|").slice(1, -1).map(c => c.trim());
      if (real.every(c => /^[-:]+$/.test(c))) return;
      const tag = i === 0 ? "th" : "td";
      const style = i === 0
        ? 'background:#f9fafb;color:#6b7280;font-weight:500;text-align:left;padding:6px 10px;border-bottom:2px solid #e5e7eb'
        : 'padding:6px 10px;border-bottom:1px solid #f3f4f6';
      html += "<tr>" + real.map(c => `<${tag} style="${style}">${c}</${tag}>`).join("") + "</tr>";
    });
    html += "</table>";
    return html;
  });
  /* 换行：Markdown 里同段落的软换行（单个 \n）默认不会断行，邮件正文里全是这种
     "写完一句回车" 的写法，不处理就会挤成一整段。块级元素（表格已整体替换、
     blockquote 每行独立成块）之间的换行也一并转成 <br>，连续空行收敛成一个。 */
  t = t.replace(/\n+/g, "<br>");
  return t;
}

/* 状态管理（2026-10-23 员工编号登录改造：email/userId/role → empId/empName/position/level）
 * ========================================================================================= */
var state = {
  sending: false,
  empId: localStorage.getItem("platform_emp_id") || "",
  empName: localStorage.getItem("platform_emp_name") || "",
  position: localStorage.getItem("platform_position") || "",
  level: localStorage.getItem("platform_level") || "",
  token: localStorage.getItem("platform_token") || "",   // JWT
};

/* 登录制：线程 id 即员工编号（匿名随机游客 id 已删——未登录在 send 入口即被拦回登录） */
function currentThreadId() {
  return state.empId;
}

/* 顶栏用户区
 * ========== */
function updateUserBar() {
  const isLogin = !!state.token;
  $("loginBtn").style.display = isLogin ? "none" : "";
  $("logoutBtn").style.display = isLogin ? "" : "none";
  $("emailText").textContent = isLogin
    ? `${state.empName || state.empId}（${state.position || "员工"}）`
    : "未登录";
}

/* 登录 / 注册弹窗
 * =============== */
/* postJson / withBtnLoading：getCode 和 submitAuth 原来各写一遍
   "fetch POST + JSON 头 + r.json() + 按钮禁用/文案/恢复 + 网络错误 toast"，
   两段结构几乎逐行对应，收敛成这两个小工具（新增接口直接复用） */
async function postJson(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

/* fn 返回 true 表示"别恢复按钮"（比如发码成功后交给倒计时接管） */
async function withBtnLoading(btn, loadingText, fn) {
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = loadingText;
  let keepDisabled = false;
  try {
    keepDisabled = (await fn()) === true;
  } catch (e) {
    toast("网络错误，请检查后端服务", "error");
  } finally {
    if (!keepDisabled) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }
}

function openModal() { $("mask").classList.add("show"); }
function closeModal() { $("mask").classList.remove("show"); }

function submitAuth() {
  const empId = $("empIdInput").value.trim();
  const pwd = $("pwdInput").value;
  if (!empId || !pwd) { toast("请填写员工编号和密码", "warn"); return; }
  if (!/^\d{10}$/.test(empId)) { toast("员工编号为 10 位数字", "warn"); return; }

  const btn = $("submitBtn");
  withBtnLoading(btn, "登录中…", async () => {
    /* FastAPI 契约：成功 200 + {token, employee_name, position, level, ...}；
       失败 4xx + {detail}（HTTPException），没有旧版 res.code 包装 */
    const res = await postJson("/auth/login", { employee_id: Number(empId), password: pwd });
    if (res.token) {
      toast("登录成功", "success");
      state.empId = empId;
      state.empName = res.employee_name || "";
      state.position = res.position || "";
      state.level = String(res.level || "");
      state.token = res.token;
      localStorage.setItem("platform_emp_id", state.empId);
      localStorage.setItem("platform_emp_name", state.empName);
      localStorage.setItem("platform_position", state.position);
      localStorage.setItem("platform_level", state.level);
      localStorage.setItem("platform_token", state.token);
      updateUserBar();
      closeModal();
      loadHistory();   /* 登录成功回填该员工线程的历史（登录制：线程=员工编号） */
      $("empIdInput").value = "";
      $("pwdInput").value = "";
    } else {
      toast(res.detail || "登录失败", "error");
    }
  });
}

function logout() {
  /* 清场三件事：关进行中的流、复位发送态、清聊天区——
     换账号不能看到上一账号的对话残留，旧流的后续帧也不许再写进新页面 */
  if (_currentEs) { try { _currentEs.close(); } catch {} _currentEs = null; }
  state.sending = false;
  setSendingUI(false);
  $("messages").innerHTML = "";
  state.empId = "";
  state.empName = "";
  state.position = "";
  state.level = "";
  state.token = "";
  ["platform_emp_id", "platform_emp_name", "platform_position", "platform_level", "platform_token"]
    .forEach(k => localStorage.removeItem(k));
  updateUserBar();
  openModal();   /* 登录制：退出后直接回到登录框 */
  toast("已退出登录", "info");
}

/* 消息渲染
 * ======== */
function addMsg(role, text) {
  const wrap = $("messages");
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML =
    `<div class="avatar">${role === "user" ? "我" : "AI"}</div>` +
    `<div class="bubble">${text}</div>`;
  wrap.appendChild(div);
  wrap.scrollTop = wrap.scrollHeight;
  return div;
}

function addBotMsg() {
  const wrap = $("messages");
  const div = document.createElement("div");
  div.className = "msg bot";
  /* 气泡外包一层 .bubble-col，下面挂「复制」按钮（hover 才浮现）。
     注意 addBotMsg 仍然返回 .bubble 本身——调用方（SSE 流式写入）依赖这个返回值，
     结构变了但契约不变。 */
  div.innerHTML =
    '<div class="avatar">AI</div>' +
    '<div class="bubble-col">' +
      '<div class="bubble"></div>' +
      '<div class="msg-actions">' +
        '<button class="act-btn" type="button" data-act="copy" title="复制这段回答">' +
          '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
            '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>' +
          '</svg><span>复制</span></button>' +
      '</div>' +
    '</div>';
  wrap.appendChild(div);
  bindCopy(div);
  wrap.scrollTop = wrap.scrollHeight;
  return div.querySelector(".bubble");
}

/* 复制回答。
   取 innerText 而不是 innerHTML：用户要的是能直接粘进文档的纯文字，
   不是一堆 <strong>/<table> 标签。 */
function bindCopy(msgRow) {
  const btn = msgRow.querySelector('[data-act="copy"]');
  const bubble = msgRow.querySelector(".bubble");
  if (!btn || !bubble) return;
  btn.addEventListener("click", async () => {
    /* 光标是流式渲染时插进去的装饰元素，复制时要排除掉，
       否则粘出来会多一个空白方块 */
    const clone = bubble.cloneNode(true);
    clone.querySelectorAll(".cursor").forEach((c) => c.remove());
    const text = (clone.innerText || "").trim();
    if (!text) { toast("这条还没有内容", "warn"); return; }
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* http 非安全上下文下 clipboard API 不可用（本地 localhost 是安全的，
         但同事用 IP 访问就会失败），退回 execCommand 老方案 */
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch {}
      document.body.removeChild(ta);
    }
    const label = btn.querySelector("span");
    btn.classList.add("done");
    if (label) label.textContent = "已复制";
    setTimeout(() => {
      btn.classList.remove("done");
      if (label) label.textContent = "复制";
    }, 1600);
  });
}

/* anchorBubble：当前这条回答的气泡元素。
   原来固定 wrap.appendChild(card)，图表只能追加到消息列表最末尾；而文字气泡在用户
   点发送的瞬间就已经创建好占位了，所以哪怕后端 chart 帧先到，图表也必然排在
   一大段分析文字【下面】，用户得先滚过四段分析才看到图。
   现在传入气泡后，把图表卡片插到「气泡所在那条消息」之前 → 图先出现，
   文字分析在下面逐步流式写出，符合先看图再读结论的阅读顺序。
   不传 anchorBubble 时保持老行为（追加到末尾），兼容其它调用方。 */
function renderChart(chart, anchorBubble) {
  if (!window.echarts) {
    toast("ECharts 组件加载失败", "error");
    return;
  }
  const wrap = $("messages");
  const card = document.createElement("div");
  card.className = "chart-card";
  /* 标题行 flex（左标题 / 右操作按钮），操作按钮：「下载 PNG」+「柱/折线切换」。
     图表经常要贴进周报，直接存原图比截图清楚；
     同一份数据支持柱状和折线两种看法，看趋势用折线、看绝对值用柱状。 */
  const showSwitch = chart.chart_type === "bar" || chart.chart_type === "line";
  card.innerHTML =
    '<div class="chart-head">' +
      '<div class="chart-title"></div>' +
      '<div class="chart-tools">' +
        (showSwitch ?
          '<button class="act-btn" type="button" data-act="switch" title="切换 柱状 / 折线">' +
            '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
              '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M8 17v-5"/><path d="M13 17V7"/><path d="M18 17v-8"/>' +
            '</svg><span class="switch-label">' + (chart.chart_type === "line" ? "看柱状" : "看折线") + '</span></button>' : "") +
        '<button class="act-btn" type="button" data-act="download" title="下载为 PNG 图片">' +
          '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">' +
            '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>' +
          '</svg>下载</button>' +
      '</div>' +
    '</div>' +
    '<div class="chart-box"></div><div class="chart-meta"></div>';
  /* anchorBubble 是 .bubble，它的父节点才是整条消息行（.msg.bot） */
  const msgRow = anchorBubble ? anchorBubble.closest(".msg") : null;
  if (msgRow && msgRow.parentNode === wrap) {
    wrap.insertBefore(card, msgRow);
  } else {
    wrap.appendChild(card);
  }
  const title = chart.title || "数据图表";
  card.querySelector(".chart-title").textContent = title;
  const box = card.querySelector(".chart-box");
  const meta = card.querySelector(".chart-meta");
  meta.innerHTML =
    `<span class="tag">${escapeHtml(chart.chart_type || "unknown")}</span>` +
    `<span>数据点: ${(chart.x_axis || []).length}</span>` +
    (chart.y_label ? `<span>Y: ${escapeHtml(chart.y_label)}</span>` : "");
  const myChart = echarts.init(box);
  /* tooltip 统一成品牌风格——深色底白字、圆角、阴影、跟随主题。
     原默认样式是白底灰框，跟整体设计语言不搭。 */
  const brandColor = getComputedStyle(document.documentElement).getPropertyValue("--brand").trim() || "#2563eb";
  const tooltipStyle = {
    backgroundColor: "rgba(15,23,42,.92)",
    borderColor: brandColor,
    borderWidth: 1,
    textStyle: { color: "#f8fafc", fontSize: 12.5 },
    padding: [8, 12],
    extraCssText: "border-radius:8px;box-shadow:0 4px 12px rgba(15,23,42,.25);",
  };

  let option;
  if (chart.chart_type === "pie") {
    option = {
      tooltip: Object.assign({ trigger: "item", formatter: "{b}: {c} ({d}%)" }, tooltipStyle),
      legend: { bottom: 0, type: "scroll" },
      series: [{
        type: "pie",
        radius: ["35%", "62%"],
        label: { formatter: "{b}\n{d}%" },
        data: (chart.x_axis || []).map((n, i) => ({ name: n, value: (chart.series || [])[i] || 0 })),
      }],
    };
  } else {
    const isLine = chart.chart_type === "line";
    option = {
      tooltip: Object.assign({ trigger: "axis" }, tooltipStyle),
      grid: { left: 10, right: 20, top: 45, bottom: 30, containLabel: true },
      xAxis: { type: "category", data: chart.x_axis || [], axisLabel: { rotate: (chart.x_axis || []).length > 6 ? 30 : 0 } },
      yAxis: {
        type: "value",
        axisLabel: { formatter: (v) => v >= 10000 ? (v / 10000) + "万" : v },
      },
      series: [{
        type: isLine ? "line" : "bar",
        data: chart.series || [],
        smooth: isLine,
        barMaxWidth: 40,
        /* 跟 --brand 保持一致，否则图表颜色比页面其余部分偏亮 */
        itemStyle: { color: brandColor, borderRadius: isLine ? 0 : [4, 4, 0, 0] },
        lineStyle: { width: 3 },
        areaStyle: isLine ? { opacity: 0.15 } : undefined,
      }],
    };
  }
  myChart.setOption(option);
  window.addEventListener("resize", () => myChart.resize());

  /* 柱/折线切换。同一份 x_axis/series，只改 series.type + 样式细节。
     切到折线时加平滑曲线和面积渐变，看趋势更直观；切回柱状恢复原样。 */
  const switchBtn = card.querySelector('[data-act="switch"]');
  if (switchBtn) {
    switchBtn.addEventListener("click", () => {
      const s = myChart.getOption().series[0];
      const toLine = s.type === "bar";
      const label = card.querySelector(".switch-label");
      myChart.setOption({
        series: [{
          type: toLine ? "line" : "bar",
          smooth: toLine,
          itemStyle: { color: brandColor, borderRadius: toLine ? 0 : [4, 4, 0, 0] },
          lineStyle: { width: 3 },
          areaStyle: toLine ? { opacity: 0.15 } : { opacity: 0 },
        }],
      });
      if (label) label.textContent = toLine ? "看柱状" : "看折线";
    });
  }

  /* 下载 PNG。用 ECharts 自带的 getDataURL 导出，
     pixelRatio:2 出两倍图，贴进 PPT/周报不糊；背景填白，否则透明底在白底文档里看不出边界。 */
  const dlBtn = card.querySelector('[data-act="download"]');
  if (dlBtn) {
    dlBtn.addEventListener("click", () => {
      try {
        const url = myChart.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#fff" });
        const a = document.createElement("a");
        a.href = url;
        a.download = `${title}_${new Date().toISOString().slice(0, 10)}.png`;
        a.click();
        toast("图表已保存", "success");
      } catch (e) {
        toast("导出失败：" + e.message, "error");
      }
    });
  }

  /* 图表现在插在文字气泡【上面】，如果还无脑滚到最底部，刚出来的图会被顶出视野。
     所以插入模式下滚到图表自己的位置；追加模式（老行为）仍滚到底。 */
  if (msgRow && msgRow.parentNode === wrap) {
    card.scrollIntoView({ block: "nearest" });
  } else {
    wrap.scrollTop = wrap.scrollHeight;
  }
}

/* 进度步骤条
 * ==========
   把 status 帧的"一句灰色文字"升级成 4 步可视化进度：理解 → 取数 → 出图/算 → 撰写。
   后端每推一个 status 帧都带 node 名（见 chat_router.py），这里按节点映射到步骤、
   标出"当前走到哪一步"。已完成的步骤点亮，当前步骤脉动，连接线跟着变色。
   只有 status 帧持续到达时才显示；首字(text)到达后整个气泡被 renderMd 覆盖，进度条自然消失。 */
const PROGRESS_STEPS = [
  { key: "understand", label: "理解" },
  { key: "fetch",      label: "取数" },
  { key: "compute",    label: "出图/算" },
  { key: "write",      label: "撰写" },
];
/* 节点 → 步骤映射：一个节点可能对应多个步骤（比如 rag 既是理解也是取数），
   取"最靠后"那个，让进度条始终往前走 */
const NODE_TO_STEP = {
  route:     "understand",
  summarize: "understand",
  rag:       "fetch",
  db:        "fetch",
  chart:     "compute",
  system_draft: "compute",
  system_send:  "compute",
  clarify:   "understand",
  writer:    "write",
  chat:      "write",
};

function renderProgressSteps(bubble, nodeName, tipText) {
  if (!bubble) return;
  const current = NODE_TO_STEP[nodeName];
  if (!current) return;
  const idx = PROGRESS_STEPS.findIndex((s) => s.key === current);
  if (idx < 0) return;

  let html = '<div class="progress-wrap"><div class="progress-steps">';
  PROGRESS_STEPS.forEach((step, i) => {
    const cls = i < idx ? "step done" : (i === idx ? "step active" : "step");
    html += `<div class="${cls}"><span class="dot"></span><span>${step.label}</span></div>`;
    if (i < PROGRESS_STEPS.length - 1) {
      html += `<div class="connector${i < idx ? " done" : ""}"></div>`;
    }
  });
  html += "</div>";
  if (tipText) {
    html += `<div class="progress-tip">${escapeHtml(tipText)}</div>`;
  }
  html += "</div>";
  bubble.innerHTML = html;
  $("messages").scrollTop = $("messages").scrollHeight;
}

/* 思考中三点动画
 * ==============
   点发送到第一个 status 帧回来之间，后端还没开始推任何进度，
   气泡里是空的。放三个跳动的小点，让用户知道"请求已收到、后台在跑"。 */
function renderThinkingDots(bubble) {
  if (!bubble) return;
  bubble.innerHTML =
    '<div class="thinking-dots"><span></span><span></span><span></span></div>';
}

function renderSystemCard(content) {
  if (!content) return;
  const wrap = $("messages");
  const card = document.createElement("div");
  card.className = "system-card";
  const sent = content.sent_count || 0;
  const recipients = content.recipients || [];
  const subject = content.subject || "";
  const summary = content.summary || "";
  /* 取消/起草失败/发送失败都是"没发出去"，共用灰色取消态；只有真发出去才是绿色"已发送"卡 */
  const cancelled = !!content.cancelled;
  const failed = !!content.failed;
  if (cancelled || failed) card.classList.add("cancelled");
  const icon = cancelled ? "🚫" : failed ? "⚠️" : "✉️";
  const title = cancelled ? "邮件已取消" : failed ? "邮件未发送" : "邮件已发送";
  let html = `<div class="sys-title"><span class="sys-icon">${icon}</span><span>${title}</span></div>`;
  html += '<div class="sys-meta">';
  if (summary) html += `<div>${escapeHtml(summary)}</div>`;
  if (recipients.length) {
    html += '<div><span style="color:var(--text-3)">收件人：</span><span class="sys-recipients">';
    recipients.forEach((r) => { html += `<span class="recipient-chip">${escapeHtml(r)}</span>`; });
    html += '</span></div>';
  }
  if (subject) html += `<div><span style="color:var(--text-3)">主　题：</span><span class="sys-subject">${escapeHtml(subject)}</span></div>`;
  html += "</div>";
  card.innerHTML = html;
  wrap.appendChild(card);
  wrap.scrollTop = wrap.scrollHeight;
}

/* 邮件草稿确认卡片 + /chat/resume 恢复流
 * ======================================
   system_send 节点 interrupt 挂起时，后端推 confirm 帧带草稿（收件人/主题/正文），
   这里渲染成确认卡片；用户点击后再发一个 fetch POST 打 /chat/resume，
   图从断点恢复，后续的 text/system 帧流回同一个气泡。 */
function renderMailConfirm(bubble, content) {
  if (!bubble || !content) return;
  const wrap = $("messages");
  const card = document.createElement("div");
  card.className = "mail-confirm-card";
  const recipients = content.recipients || [];
  let html = '<div class="mc-title"><span>📧</span><span>邮件待确认</span></div>';
  html += '<div class="mc-meta">';
  html += `<div><span class="mc-field">收件人：</span><span class="mc-recipients">${
    recipients.map((r) => `<span class="recipient-chip">${escapeHtml(r)}</span>`).join("")
  }</span></div>`;
  /* 未绑邮箱提醒（2026-10-23 定稿）：职位群发时这些人收不到，发件人确认前看得见 */
  const noEmail = content.no_email || [];
  if (noEmail.length) {
    html += `<div style="color:#b45309"><span class="mc-field">提　醒：</span>`
         +  `以下人员未绑定邮箱，将收不到：${escapeHtml(noEmail.join("、"))}</div>`;
  }
  /* @ 直放地址没过员工库校验（可能是外部邮箱或拼错的地址），确认前必须肉眼核对 */
  const external = content.external || [];
  if (external.length) {
    html += `<div style="color:#b45309"><span class="mc-field">注　意：</span>`
         +  `以下地址未在员工库中登记，请核对后再发：${escapeHtml(external.join("、"))}</div>`;
  }
  html += `<div><span class="mc-field">主　题：</span><span class="mc-subject-val">${escapeHtml(content.subject || "（无主题）")}</span></div>`;
  html += "</div>";
  /* 正文用 renderMd 渲染（邮件正文是 AnlyzeAgent 写的 Markdown）；
     空草稿给一个占位提示，避免预览区整块空白 */
  const bodyHtml = content.content ? renderMd(content.content) : '<span style="color:var(--text-3)">（正文为空）</span>';
  html += `<div class="mc-preview">${bodyHtml}</div>`;
  html += '<div class="mc-hint">请核对收件人与正文，确认后将立即发送</div>';
  html += '<div class="mc-actions">'
       +  '<button class="btn btn-primary btn-sm mc-ok">确认发送</button>'
       +  '<button class="btn btn-ghost btn-sm mc-no">暂不发送</button>'
       +  "</div>";
  card.innerHTML = html;
  wrap.appendChild(card);
  wrap.scrollTop = wrap.scrollHeight;

  const titleText = card.querySelector(".mc-title span:last-child");
  const okBtn = card.querySelector(".mc-ok");
  const noBtn = card.querySelector(".mc-no");
  const decide = (action) => {
    /* 防重复点击：两个按钮一起禁用，卡片标题同步状态 */
    okBtn.disabled = true;
    noBtn.disabled = true;
    if (action === "cancel") {
      card.classList.add("cancelled");
      titleText.textContent = "已取消发送";
    } else {
      titleText.textContent = "邮件发送中…";
    }
    /* 之前的进度气泡（理解/取数步骤条）已完成使命，清空并隐藏，
       resume 流确认发送时再显示；取消则不再显示（结果看灰色取消卡片） */
    bubble.innerHTML = "";
    bubble.classList.add("bubble-hidden");
    resumeMail(action, bubble);
  };
  okBtn.onclick = () => decide("confirm");
  noBtn.onclick = () => decide("cancel");
}

/* consumeSSE：send()/resumeMail() 共用的 SSE 消费骨架（原两处约 90 行双胞胎样板收于此）。
   内置通用件：流式累加渲染（acc 逐字累加 + rAF 合批重绘，避免逐字帧 O(n²) 重排卡顿）、
   进度计时器（"已用 N 秒"）、cleanup（关流/清计时器/最终渲染/复位 sending，幂等）、
   _currentEs 登记（供「停止生成」关闭）、error/done/status/system 四种通用帧。
   调用方只传差异：
   - onFrame(d, helpers)：专有帧（chart/clarify/confirm…），返回 true 表示已消费；
     未消费的非通用帧按 text 帧处理（逐字累加进气泡）。
   - onFail()：连接失败/HTTP 非 2xx 的差异处理（send 自动重连 / resumeMail 提示）；
     骨架先清 _currentEs 引用再回调，仅当仍在 sending 时触发。
   suppressBubble：取消恢复流专用——气泡保持隐藏，状态/正文帧不顶出气泡。 */
function consumeSSE({ url, body, bubble, suppressBubble = false, onFrame = null, onFail = null }) {
  state.sending = true;
  setSendingUI(true);
  let acc = "";
  let gotText = false;
  let systemRendered = false;
  let rafId = null;
  let errored = false;
  const paint = (withCursor) => {
    bubble.innerHTML = renderMd(acc) + (withCursor ? '<span class="cursor"></span>' : "");
    $("messages").scrollTop = $("messages").scrollHeight;
  };
  const schedulePaint = () => {
    if (rafId != null) return;
    rafId = requestAnimationFrame(() => { rafId = null; paint(true); });
  };
  let stream = null;
  /* 进度计时器：取数/出图常耗时十几秒，用「已用 N 秒」让用户确认系统仍在工作。
     只在显示进度条（未收到正文/确认卡）时跑，其余时机清除。 */
  let progressTimer = null;
  let progressStart = 0;
  let progressCtx = null;   // { node, tip }
  const stopProgressTimer = () => {
    if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
  };
  const startProgressTimer = (node, tip) => {
    progressCtx = { node, tip };
    progressStart = Date.now();
    stopProgressTimer();
    progressTimer = setInterval(() => {
      if (!progressCtx || gotText) { stopProgressTimer(); return; }
      const sec = Math.round((Date.now() - progressStart) / 1000);
      /* 只更新提示文本，避免每秒整体重建 DOM 导致动画闪烁 */
      const tipEl = bubble.querySelector(".progress-tip");
      if (tipEl) {
        tipEl.textContent = `${progressCtx.tip}（已用 ${sec} 秒）`;
      } else {
        renderProgressSteps(bubble, progressCtx.node, `${progressCtx.tip}（已用 ${sec} 秒）`);
      }
    }, 1000);
  };
  const cleanup = () => {
    if (stream) stream.close();
    if (_currentEs === stream) _currentEs = null;
    stopProgressTimer();
    /* 收尾：取消未执行的合批，已收到正文且非错误则做一次不带光标的最终渲染 */
    if (rafId != null) { cancelAnimationFrame(rafId); rafId = null; }
    if (gotText && !errored) paint(false);
    state.sending = false;
    setSendingUI(false);
  };
  stream = openSSE(
    url,
    body,
    (d) => {
      if (d.error) {
        errored = true;
        /* 出错要让用户看见：把隐藏的气泡放回来显示错误（取消路径出错也一样） */
        bubble.classList.remove("bubble-hidden");
        bubble.classList.add("error-msg");
        bubble.textContent = d.content || "服务出错";
        cleanup();
        return;
      }
      if (d.done) { cleanup(); return; }
      switch (d.type) {
        case "status":
          /* 后端节点进度提示：真正的 text 帧到达（gotText=true）后就不再覆盖；
             取消恢复流气泡保持隐藏，进度不显示。 */
          if (!suppressBubble && !gotText && d.content) {
            bubble.classList.remove("bubble-hidden");
            renderProgressSteps(bubble, d.node, d.content);
            startProgressTimer(d.node, d.content);
          }
          break;
        case "system":
          stopProgressTimer();
          if (!systemRendered) { renderSystemCard(d.content); systemRendered = true; }
          break;
        default:
          /* 专有帧先交调用方（chart/clarify/confirm…）；未消费的按 text 帧处理：
             逐字增量只累加（真流式下同一段回答拆成几百帧增量推过来，覆盖就只剩最后一个字），
             重绘收敛到每帧一次（schedulePaint）。 */
          if (onFrame && onFrame(d, { stopProgressTimer })) break;
          if (d.content && !suppressBubble) {
            gotText = true;
            stopProgressTimer();
            bubble.classList.remove("bubble-hidden");
            acc += d.content;
            schedulePaint();
          }
      }
    },
    (err) => {
      /* F1：出错先清旧流的进度计时器和未执行的合批重绘——不清的话自动重连后，
         新闭包的 stopProgressTimer 清不掉旧闭包的 timer，旧 timer 每秒把已失效的
         进度条重画回气泡、跟新流的状态帧互相覆盖。
         注意不能在这里调整个 cleanup()：它会复位 state.sending，
         下面的 onFail（自动重连）就永远不触发了 */
      stopProgressTimer();
      if (rafId != null) { cancelAnimationFrame(rafId); rafId = null; }
      if (_currentEs === stream) _currentEs = null;
      /* 会话中 token 过期/改密失效 → 后端 401：提示并弹登录框重新登录 */
      if (err && String(err.message).indexOf("401") !== -1) {
        toast("登录已失效，请重新登录", "warn");
        openModal();
      }
      if (state.sending && onFail) onFail();
    },
    cleanup,   /* 流自然结束兜底复位（与 done 帧共用 cleanup，幂等） */
  );
  _currentEs = stream;   /* 存引用供「停止生成」按钮关闭 */
  return stream;
}

/* /chat/resume 的恢复流：帧类型是 /chat 的子集（status/text/system/done/error），
   无专有帧要处理（onFrame 缺省），差异只有取消路径的隐藏气泡（suppressBubble）与失败提示。 */
function resumeMail(action, bubble) {
  const threadId = currentThreadId();
  /* 取消动作：后端只是把图以「取消」恢复并留痕，不再有需要写进气泡的回答，
     气泡保持隐藏，结果完全由灰色系统卡片表达。确认动作：后续状态/正文要写进气泡。 */
  const suppressBubble = action === "cancel";
  consumeSSE({
    url: "/chat/resume",
    body: { thread_id: threadId, action },
    bubble,
    suppressBubble,
    onFail: () => {
      if (!suppressBubble) {
        bubble.classList.remove("bubble-hidden");
        bubble.classList.add("error-msg");
        bubble.textContent = "连接失败，请检查后端服务是否运行";
      } else {
        /* 取消路径连接失败：提示收口到 toast，不打扰已有布局 */
        toast("取消请求失败，请重试", "error");
      }
      state.sending = false;
      setSendingUI(false);
    },
  });
}

/* 核心：SSE 发送（带自动重连）
 * ============================ */
async function send() {
  if (state.sending) return;
  /* 登录制：未登录一律拦回登录框（后端 /chat 无 token 也是 401，这里先拦省一趟） */
  if (!state.token) { toast("请先登录", "warn"); openModal(); return; }
  const input = $("input");
  const q = input.value.trim();
  if (!q) return;
  input.value = "";
  input.style.height = "24px";
  addMsg("user", escapeHtml(q));

  const bubble = addBotMsg();
  /* 发起新问题时，把还挂着的邮件确认卡片按钮置灰禁用——
     后端 /chat 会把未确认的草稿按「取消」自动恢复，旧卡片再点已经没有断点可恢复 */
  document.querySelectorAll(".mail-confirm-card .mc-actions button").forEach((b) => { b.disabled = true; });
  /* 发送后立刻放三点动画，避免"点了没反应"的空窗期 */
  renderThinkingDots(bubble);
  const threadId = currentThreadId();
  let chartRendered = false;

  /* B1 修复：断线重连不再走 send()——send 入口被 sending 闸 + input 已空双重拦截，
     重连 100% 不生效（页面卡发送态只能手动停止）。改为闭包内 openStream 用已保存的
     q/threadId/bubble 直接重开 SSE 流；chartRendered 闭包共享，重连后 chart 帧不重复渲染。 */
  function openStream(retry) {
    consumeSSE({
      url: "/chat",
      body: { question: q, thread_id: threadId },
      bubble,
      onFrame: (d, helpers) => {
        switch (d.type) {
        case "chart":
          if (!chartRendered) {
            console.log("[CHART] renderChart 被调用，content:", d.content);
            try {
              renderChart(d.content, bubble);
              chartRendered = true;
              console.log("[CHART] 渲染成功");
              /* 图表生成失败时（EchartsAgent 3 次重试都炸），d.content.fallback_reason
                 会有值；普通 ChartData 不会有这字段。两类提示分别处理：
                 - 兜底 ChartData（fallback_reason 有值）→ toast warn 提示，并保留图表卡片占位
                 - 真图表（无 fallback_reason）→ 不弹 toast，只走自动诊断 */
              if (d.content && d.content.fallback_reason) {
                toast("图表生成失败：" + d.content.fallback_reason, "warn", 5000);
              }
              /* 自动修复：容器 0 尺寸/ECharts 没正确显示 → 强制 resize + 重画。
                 取最后一个 .chart-box（刚刚 echarts.init 的那个 DOM），getInstanceByDom 才能拿到实例
                 ——选择器必须匹配 renderChart 生成的 class。 */
              setTimeout(() => {
                const boxes = document.querySelectorAll(".chart-card .chart-box");
                const chartBox = boxes.length ? boxes[boxes.length - 1] : null;
                if (chartBox) {
                  const r = chartBox.getBoundingClientRect();
                  console.log("[CHART] 容器尺寸:", r.width, "x", r.height);
                  const inst = echarts.getInstanceByDom(chartBox);
                  if (inst) {
                    if (r.width === 0 || r.height === 0) {
                      console.warn("[CHART] 容器 0 尺寸，强制设高度 + resize");
                      chartBox.style.height = "350px";
                      chartBox.style.width = "100%";
                    }
                    inst.resize();
                    console.log("[CHART] resize 完成");
                  } else {
                    console.warn("[CHART] 没找到 ECharts 实例，容器可能未初始化");
                  }
                }
              }, 200);
            } catch (e) {
              console.error("[CHART] 渲染失败:", e, "content=", d.content);
            }
          }
          return true;
        case "clarify": {
          /* 反问正文（含编号候选）已由 text 帧渲染进气泡，这里补一句输入引导 */
          const tip = document.createElement("div");
          tip.className = "clarify-tip";
          tip.textContent = "💡 可回复序号选择，或直接补充你的问题";
          bubble.parentNode.appendChild(tip);
          $("messages").scrollTop = $("messages").scrollHeight;
          return true;
        }
        case "confirm":
          /* 邮件草稿确认卡片（确定发送/取消）。
             收到这帧后本轮 SSE 就结束了，等用户点击后走 /chat/resume 恢复 */
          helpers.stopProgressTimer();
          renderMailConfirm(bubble, d.content);
          return true;
        case "sql_trace":
          /* 后端不再推 sql_trace 帧。保留空分支只为兼容极端情况——老页面缓存未刷新时收到旧帧，
             直接忽略即可，不能掉到 default 分支去当正文文字渲染。 */
          return true;
        }
        return false;   /* 未匹配帧落回骨架按 text 帧处理 */
      },
      onFail: () => {
        /* 自动重连（最多 3 次）：用闭包保存的 q/threadId 直接重开 SSE，不经 send() 入口闸 */
        if (retry < 3) {
          bubble.innerHTML = `<span style="color:#f59e0b">连接中断，${1.5 * (retry + 1)}s 后重试 (${retry + 1}/3)…</span>`;
          setTimeout(() => {
            /* 等待重连期间用户点了「停止」（sending 已复位）→ 放弃重连 */
            if (!state.sending) return;
            bubble.innerHTML = "";
            renderThinkingDots(bubble);
            openStream(retry + 1);
          }, 1500 * (retry + 1));
        } else {
          bubble.classList.add("error-msg");
          bubble.textContent = "连接失败，请检查后端服务是否运行";
          state.sending = false;
          setSendingUI(false);
          toast("连接失败", "error");
        }
      },
    });
  }
  openStream(0);
}

/* 停止生成。发送中把「发送」键换成「停止」键，
   点击后关闭 fetch 流，让用户能立刻打断一次跑偏的分析（比如问错了）。 */
let _currentEs = null;

function stopGenerating() {
  if (_currentEs) {
    try { _currentEs.close(); } catch {}
    _currentEs = null;
  }
  state.sending = false;
  setSendingUI(false);
  toast("已停止生成", "warn", 2000);
}

function setSendingUI(isSending) {
  const btn = $("sendBtn");
  if (isSending) {
    btn.disabled = false;   /* 不禁用——这次点它是「停止」而不是「发送」 */
    btn.title = "停止生成";
    btn.onclick = stopGenerating;   /* 临时接管 onclick，send() 时恢复 */
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>';
  } else {
    btn.disabled = false;
    btn.title = "发送（Enter）";
    btn.onclick = send;   /* 恢复默认行为 */
    btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M2 21l21-9L2 3v7l15 2-15 2v7z" fill="currentColor"/></svg>';
  }
}

/* 推荐问题原样发送、不拼任何口径后缀：问题没带时间范围时，
   后端 db/chart 智能体默认按最近30天查（见各 agent 的 system prompt）。 */

function toggleSuggestCollapse() {
  const list = $("suggestList");
  const btn = $("collapseBtn");
  const collapsed = list.classList.toggle("collapsed");
  btn.classList.toggle("collapsed", collapsed);
  btn.querySelector("span:last-child").textContent = collapsed ? "展开" : "收起";
  try { localStorage.setItem("platform_suggest_collapsed", collapsed ? "1" : "0"); } catch {}
}
function restoreSuggestState() {
  try {
    if (localStorage.getItem("platform_suggest_collapsed") === "1") {
      const list = $("suggestList");
      const btn = $("collapseBtn");
      list.classList.add("collapsed");
      btn.classList.add("collapsed");
      btn.querySelector("span:last-child").textContent = "展开";
    }
  } catch {}
}

/* 推荐问题点击（事件委托） */
$("suggestList").addEventListener("click", (e) => {
  const el = e.target.closest(".suggest");
  if (!el || state.sending) return;
  $("input").value = el.dataset.q || "";
  send();
});


function showModal(html) {
  const mask = $("mask");
  const modal = mask.querySelector(".modal");
  modal.innerHTML = html;
  modal.style.width = "640px";
  modal.style.maxHeight = "85vh";
  modal.style.overflowY = "auto";
  mask.classList.add("show");
}

/* ECharts 多源 CDN 加载
 * ===================== */
(function loadECharts() {
  const urls = [
    "/static/js/lib/echarts.min.js",   // 本地优先：不依赖外网，演示永不翻车
    "https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js",
    "https://cdn.bootcdn.net/ajax/libs/echarts/5.5.0/echarts.min.js",
    "https://unpkg.com/echarts@5.5.0/dist/echarts.min.js",
  ];
  let i = 0;
  function next() {
    if (window.echarts) return;
    if (i >= urls.length) { console.warn("echarts 加载失败，图表将无法显示"); return; }
    const s = document.createElement("script");
    s.src = urls[i++];
    s.onload = next;
    s.onerror = next;
    document.head.appendChild(s);
  }
  next();
})();

/* 重开页面回填历史
 * ================
   消息本来只活在当前页面 DOM 里，刷新即空；后端 checkpoint 还留着未截断的轮次，
   启动时拉一次按原样渲染成气泡。已截断归档的更早期轮次拿不回来（在冷层向量库），
   deleted>0 时给一行提示。拉取失败静默——不挡正常聊天。 */
async function loadHistory() {
  try {
    const headers = {};
    if (state.token) headers["Authorization"] = "Bearer " + state.token;
    const threadId = currentThreadId();
    const resp = await fetch("/chat/history?thread_id=" + encodeURIComponent(threadId), { headers });
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.deleted > 0) {
      addMsg("bot", `（更早的 ${data.deleted} 轮对话已归档，不再展示；直接提问即可，模型仍记得要点）`);
    }
    (data.turns || []).forEach((t) => {
      addMsg("user", escapeHtml(t.q));
      const bubble = addBotMsg();
      bubble.innerHTML = renderMd(t.a || "");
    });
    const wrap = $("messages");
    wrap.scrollTop = wrap.scrollHeight;
  } catch { /* 服务未就绪/无历史都不处理 */ }
}

/* 启动
 * ==== */
updateUserBar();
startHealthCheck();
restoreSuggestState();
initScrollWatcher();   /* 回到底部按钮的滚动监听 */
/* 登录制：进来先登录；有 token 才回填历史（无 token 拉历史只会吃 401） */
if (!state.token) openModal(); else loadHistory();

/* 输入框事件 */
const input = $("input");
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (!state.sending) send();
  }
});
input.addEventListener("input", function () {
  this.style.height = "24px";
  this.style.height = Math.min(this.scrollHeight, 140) + "px";
});

/* 关闭弹窗：按 Esc */
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeModal();
});

/* 页面卸载：清理心跳 */
window.addEventListener("beforeunload", () => {
  if (healthCheckTimer) clearInterval(healthCheckTimer);
});

/* 窗口可见性变化：不再触发心跳检测（避免 ERR_ABORTED 噪声；
   60s 周期心跳 + 启动时一次 已经足够，错过几次不影响） */
