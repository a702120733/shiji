# analysis.json

每条分析保存到 `notes/<id>/analysis.json`。从 review.json 复制 note_id 和 fingerprint，其余由 Codex 阅读素材后填写。路径相对于资料库根目录，必须来自 review.json。

```json
{
  "note_id": "24位笔记ID",
  "fingerprint": "review.json 的 fingerprint",
  "category": "家居",
  "subcategory": "空间布局",
  "tags": ["loft", "小户型"],
  "summary": "小户型布局 · 垂直收纳 · 动线优化 · 可拆家具",
  "key_points": ["明确收纳位置与使用动线"],
  "takeaways": ["可复用信息，没有则空数组"],
  "limitations": [],
  "coverage": {
    "status": "complete",
    "read_text": true,
    "reviewed_images": ["notes/ID/media/ID/ID_1.jpg"],
    "reviewed_frame_sheets": ["notes/ID/derived/video-1-sheet-1.jpg"],
    "read_transcripts": ["notes/ID/derived/video-1-transcript.json"]
  }
}
```

category、summary 必填非空；subcategory 为字符串，所有文本数组可为空。未阅读的材料不能填入已查看路径。complete 验证证据全覆盖及采集/预处理状态；partial 必须有至少一条 limitation。脚本无法证明模型实际查看过素材，执行者必须真实阅读再填写。无正文时 read_text 可为 false；无某类素材时对应数组为空。

fingerprint 包含正文、原始素材内容哈希和预处理参数/结果。素材、正文、转写或采样变化后，旧分析失效，pending 会重新列出。只变化签名 URL 不影响分析。render 拒绝未知或越界证据路径，不渲染失效分析；修正后可再次 render。

summary 面向列表阅读，优先 3–6 个词组，用“ · ”分隔；不能把广告宣称或主观评测省略成已验证结论。category 与 tags 平铺展示，subcategory 只供数据兼容。作者主页来自 authors.json，不写入 analysis.json，也不改分析指纹。
