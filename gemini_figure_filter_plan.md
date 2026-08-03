# Gemini 3 Flash 截图分类 - 论文图注过滤方案

## 一、问题背景

当前 pdf_parser.py 用正则+规则从PDF提取图片，存在根本局限。
_is_text_reference() 靠有限动词列表判断，总会遗漏新格式。

## 二、解决方案

用 Gemini 3 Flash 视觉理解替代规则函数。
流程：正则找候选行(不变) -> 页面截图 -> Gemini分类 -> 保留caption -> 后续不变

实测：
- 图注 "Fig. 2. Atomic resolution..." -> caption (正确, 9.4s)
- 正文引用 "...shown in Fig. 1(a)..." -> reference (正确, 4.5s)

## 三、API配置

- 位置: config_local.py (已有)
- Key: GEMINI_API_KEY
- URL: https://opencode.ai/zen/v1/models/gemini-3-flash
- 请求格式: Gemini native (contents + inline_data)
- 认证: x-goog-api-key header

## 四、改动清单

### pdf_parser.py

1. 新增 _llm_filter_captions(page, candidates, page_num, pdf_path)
   - 检查缓存，命中直接返回
   - 截图 -> base64 -> 调用 Gemini
   - 解析JSON结果，应用过滤
   - 失败回退 _heuristic_filter()

2. 新增 _heuristic_filter(candidates) - 旧规则回退

3. 修改 parse_pdf() Phase 2 Step 1:
   原: for c in caption_matches: if _is_text_reference(...)
   改: caption_matches = _llm_filter_captions(...)

### ai_reader.py

新增 gemini_classify_captions(page_b64, candidates_text, config)
   - 构建 prompt，调用 Gemini API
   - 返回结构化 JSON

## 五、Prompt设计

`
你是物理学论文排版专家。判断每行是图注还是正文引用。

图注特征：独立成行，位于图片下方，以 Fig. X. 或 Figure X: 开头。
正文引用特征：嵌入在段落中，前后有文字，常带动词。

候选行：
[格式化列表]

回答JSON格式：
{"results": [{"fig": "1", "type": "caption"}]}
`

## 六、截图方法

`python
page = doc[page_num]
pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
img_bytes = pix.tobytes("png")
b64 = base64.b64encode(img_bytes).decode()
`

典型大小 200-500KB，<Gemini 20MB限制。

## 七、缓存

cache/gemini_fig_filter/{pdf_hash}_p{page_num}.json
key = MD5(pdf_path)[:12] + "_" + str(page_num)

## 八、回退机制

任何异常 -> 回退到旧规则(不中断流程)
GEMINI_FILTER_ENABLED 常量可控制总开关

## 九、已知边缘情况

- "Fig. 1(b), which remain..." -> reference (旧规则漏过滤)
- "Figure 1: P2TANG polymer..." -> caption (冒号格式)
- "FIG 1 | Band engineering..." -> caption (Nature格式)
- "as shown in Figure S1" -> reference (补充材料)

## 十、注意事项

1. OpenCode代理转发，非直接Google API
2. 不要并发调用
3. pdf_parser内部不要调db.get_connection()
4. 删除旧记录 -> 再解析 -> 再插入(顺序重要)
