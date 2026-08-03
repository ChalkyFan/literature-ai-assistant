# 文献AI助手 前端改进方案

> 本文档由代码审查生成，供开发执行。
> 涉及文件：`web/static/style.css`（1987 行）、`web/templates/base.html`、`index.html`、`all.html`、`paper.html`、`my.html`。
> 不涉及后端逻辑与认证机制改动。

---

## 当前状态总览（审查结论）

| 指标 | 现状 |
|---|---|
| CSS 体积 | 单文件 1987 行，无分块 |
| 响应式 | **0 个 `@media` 查询**，全站无移动端适配 |
| 颜色 | 25+ 种硬编码；蓝色有 3 个版本（#1a56db / #3b82f6 / #2563eb），浅边框有 4 个版本 |
| 交互反馈 | 约 10 处 `location.reload()`；13+ 处原生 `alert()` |
| 主题 | 仅亮色，无暗色模式 |
| 字体 | 系统字体栈，无设计感 |

---

## 一、高优先级（体验硬伤）

### 1. 全站无移动端适配（最严重）

**现状证据**：`style.css` 中 `@media` 数量为 0，布局按桌面宽度硬渲染。

**手机上的具体问题**：
- 导航栏溢出：`.nav-inner` 为 `max-width:1100px` + 固定 `gap:24px`，内含品牌名 + 4 链接 + 180px 搜索框 + 用户徽章 + logo，375px 宽屏幕横向溢出。
- 弹窗比屏幕宽：Ask AI 弹窗 `width:380px`、登录弹窗 inline `width:420px`，超出手机可视区。
- 卡片底部操作栏挤爆：`.paper-footer` 横向 flex（状态 + 星标 + 报告点 + 组会按钮 + 查看详情），窄屏挤成一团。
- 关键词管理表格无横向滚动容器，手机上被截断。

**改法建议**：
```css
@media (max-width: 768px) {
    .nav-inner { flex-wrap: wrap; height: auto; padding: 8px 0; }
    .nav-search { order: 3; width: 100%; }
    .search-input { width: 100%; }
    .paper-card { padding: 14px 16px; }
    .paper-footer { flex-wrap: wrap; }
    .ask-ai-popup, .upload-modal-content { width: calc(100vw - 32px); max-width: 100%; }
    .figure-grid { grid-template-columns: 1fr; }
}
@media (max-width: 480px) {
    /* 更小屏：字号、间距、按钮尺寸再收紧 */
}
```
可选进阶：窄屏时导航折叠为汉堡菜单。

**工作量**：约半天（纯 CSS + 少量模板 class 调整）。

---

### 2. 交互全部靠 `location.reload()`

**现状证据**：全站约 10 处 `location.reload()`（base.html 1027/1143/1475/1960/2035/2060/2100 行等）。典型代码（index.html）：
```javascript
function toggleStar(id) {
    fetch("/api/paper/" + id + "/star", {...})
    .then(d => { if(d.ok) location.reload(); });
}
```

**具体痛点**：
- 点一次星标 = 整页重刷：白屏闪烁、滚动位置丢失、图片重新下载。
- 连续快速点击时，前一次 reload 打断第二次点击。
- 打标签、组会报告、改状态同样全量刷新；操作成功与否没有即时反馈。

**改法建议：乐观更新（Optimistic UI）**
```javascript
function toggleStar(id) {
    var icon = document.getElementById("star-" + id);
    var prev = icon.classList.contains("active");
    icon.classList.toggle("active");   // 1. 先改 UI
    fetch("/api/paper/" + id + "/star", { ... })
    .then(d => {
        if (!d.ok) { icon.classList.toggle("active"); showToast("操作失败", "error"); }
    })
    .catch(() => { icon.classList.toggle("active"); showToast("网络错误", "error"); }); // 2. 失败回滚
}
```
- 星标：切换 SVG 填充色 + scale 弹跳动画。
- 标签：切换高亮 class；报告圆点：增删元素。
- 仅"删除论文""立即更新"等破坏性操作保留确认弹窗。

**工作量**：4-5 个交互点，每个 10-15 行 JS，约半天。

---

### 3. 缺少统一反馈机制（Toast）

**现状证据**：
- 13+ 处原生 `alert()`（base.html 1455/1465/1485/1555/1560/1570/1685/2530/2535/2560/2590/2660/2665 行等）。
- 成功操作完全无提示（星标、标签、收藏成功后静默刷新）。
- 长任务提示模式割裂：上传用 inline 进度条、Ask AI 用 loading 文字、详细分析用按钮文字变化。

**具体痛点**：
- `alert()` 阻塞 JS 线程、样式不可控、每次都要手动点确定，连续操作体验极差。
- 成功/失败/加载反馈方式不统一，用户不知道何时该等、何时完成。

**改法建议**：
```html
<!-- base.html 底部加容器 -->
<div id="toast-container" style="position:fixed;top:16px;right:16px;z-index:9999;"></div>
```
```javascript
function showToast(msg, type) {
    var el = document.createElement("div");
    el.className = "toast toast-" + type;   // success / error / info
    el.textContent = msg;
    document.getElementById("toast-container").appendChild(el);
    setTimeout(function() { el.classList.add("show"); }, 10);
    setTimeout(function() { el.remove(); }, 2500);
}
```
```css
.toast { padding:10px 16px; border-radius:8px; color:#fff; margin-bottom:8px;
         opacity:0; transform:translateY(-8px); transition:all .25s; }
.toast.show { opacity:1; transform:none; }
.toast-success { background:#16a34a; }
.toast-error   { background:#dc2626; }
.toast-info    { background:#3b82f6; }
```
然后全局替换所有 `alert()` 为 `showToast()`，并给关键操作补成功提示（"已收藏 ⭐"、"已加入组会报告"、"已删除"）。

**工作量**：一次性三段代码 + 全局替换，约 1-2 小时。

---

### 4. 颜色硬编码 + 无设计变量

**现状证据**：
- `style.css` 中 25+ 种颜色，模板里还有大量 inline style。
- 同一个蓝色 3 个版本：`#1a56db`（主按钮）、`#3b82f6`（链接）、`#2563eb`（登录 Tab）。
- 同一种浅边框 4 个版本：`#eee`、`#e2e8f0`、`#f0f0f0`、`#ddd`。

**具体痛点**：
- 换品牌色 = 3 个文件 find-replace，永远改不干净。
- 没有变量就做不了暗色模式。
- `#666`/`#888`/`#999` 混用，次要文字视觉不统一。

**改法建议**：在 `style.css` 顶部定义设计令牌：
```css
:root {
    --primary:        #1a56db;   /* 主色 */
    --primary-light:  #3b82f6;   /* 链接/次主色 */
    --bg:             #f5f5f7;   /* 页面背景 */
    --card-bg:        #ffffff;   /* 卡片背景 */
    --text:           #1d1d1f;   /* 主文字 */
    --text-secondary: #6b7280;   /* 次要文字 */
    --border:         #e5e7eb;   /* 统一边框 */
    --radius:         10px;      /* 统一圆角 */
    --shadow-card:    0 1px 3px rgba(0,0,0,0.06);
    --shadow-hover:   0 4px 16px rgba(0,0,0,0.12);
}
```
逐步替换硬编码值。完成后暗色模式只需一个覆盖块：
```css
[data-theme="dark"] {
    --bg: #0f172a; --card-bg: #1e293b;
    --text: #e2e8f0; --border: #334155; ...
}
```

**工作量**：机械替换（可用正则批量），约 2-3 小时。

---

## 二、中优先级（视觉美观）

### 5. 卡片视觉层级单一
- **现状**：星标、arXiv ID、标题、作者、一句话、footer 全在同一层级。
- **改法**：标题加大加粗；一句话摘要保留彩色左边框；作者行淡化；卡片 hover 加 `translateY(-2px)` + 阴影加深。

### 6. 空状态太朴素
- **现状**：`empty-state` 只有灰色文字。
- **改法**：加 SVG 插图或大 emoji + 行动按钮（"去搜索"、"等待今日抓取"）。

### 7. 无加载骨架屏
- **现状**：页面跳转/详细分析生成期间是白屏或等待文字。
- **改法**：列表页用骨架卡片（CSS shimmer 动画）；详细分析生成时用 spinner + 进度文案。

### 8. 字体和排版单调
- **现状**：系统字体栈，无字重对比。
- **改法**：引入 Inter / Noto Sans SC（本地化部署，避免 CDN 依赖）；标题 600-700 字重、正文 400、行高统一。

### 9. 无暗色模式
- **现状**：仅亮色。
- **改法**：CSS 变量化后加 `[data-theme="dark"]` + localStorage 持久化 + 导航栏切换按钮。

---

## 三、实用功能增强（低成本高收益）

### 10. 首页日期导航缺失
- 首页只显示"今天"，无法回看前几天。
- 改法：header 加 `← 前一天 | 2026-08-03 | 后一天 →`，链接到 `?date=YYYY-MM-DD`（后端已支持该参数，只缺 UI）。

### 11. 论文详情页缺"打开 PDF / 原文链接"按钮
- 改法：detail-actions 区加"📄 本地 PDF"（`/papers/...`）和"🔗 arXiv 原文"按钮。

### 12. 图注过长被截断且无展开
- 改法：grid 里 `-webkit-line-clamp: 2` 截断 + 点击展开；lightbox 已显示完整 caption。

### 13. Lightbox 缺缩放/下载
- 改法：滚轮缩放 / 点击放大、下载原图按钮、caption 自动换行。

### 14. 搜索无高亮、无防抖
- 改法：结果中高亮匹配片段；输入框 300ms 防抖（可选实时建议）。

### 15. `/all` 分页无总页数/页码
- 改法：显示"共 X 篇 · 第 N / M 页"，页码按钮 1-5 跳跃。

### 16. "我的"页面 Tab 状态不持久
- 改法：URL hash（`#report`）或 localStorage 记住当前 tab。

### 17. AI 问答答案纯文本，格式丢失
- 改法：问答区复用 KaTeX + 简单 Markdown 渲染（如 marked.js 本地化），与详细分析保持一致。

### 18. 状态筛选缺失
- 改法：toolbar 加"全部 / 未读 / 已读"筛选 chips（后端 `status` 字段现成）。

### 19. 无键盘快捷键
- 改法：论文详情页加 `j/k` 上下一篇、`s` 收藏、`f` 聚焦搜索（左右键切图已有）。

---

## 四、实施顺序建议

- **第一批（体验质变，约 1.5 天）**：
  1. 先做 #4 CSS 变量化（后面所有样式改动的基础）
  2. #1 响应式适配
  3. #3 Toast 反馈机制
  4. #2 交互去 reload（乐观更新）
- **第二批（颜值，约 1 天）**：
  5. #5 卡片层级
  6. #6 空状态
  7. #8 字体
  8. #9 暗色模式
- **第三批（功能，按需选做）**：#10-#19

---

## 验收标准

- [ ] 手机（375px 宽）打开首页、详情页、我的页无横向滚动、无弹窗溢出
- [ ] 星标/标签/组会报告操作不再整页刷新，有即时 UI 反馈
- [ ] 所有 `alert()` 已替换为 Toast，关键操作有成功提示
- [ ] CSS 中不再出现新的硬编码颜色（旧值逐步替换中）
- [ ] 暗色模式可切换且刷新后保持
- [ ] 首页支持前后日期导航
- [ ] 详情页有"本地 PDF / arXiv 原文"入口
- [ ] 搜索结果高亮命中关键词
- [ ] `/all` 显示总页数和页码
- [ ] 我的页 Tab 刷新后保持
- [ ] AI 问答支持 Markdown/公式渲染
- [ ] 图注截断可展开，Lightbox 可缩放下载
