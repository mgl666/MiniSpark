---
name: bilibili-hot
description: 查询当前B站热搜榜并整理输出前十条。
triggers:
  - "B站热搜"
  - "哔哩哔哩热搜"
  - "B站热搜前十"
---

# B站热搜 Top 10

按以下步骤查询：

1. 调用 `web_fetch`：`https://s.search.bilibili.com/main/hotword`。
2. 榜单位于 `list` 数组中，每条包含：
   - `show_name`：热搜词
   - `heat_score`：热度
   - `word_type`：类型，可忽略
3. 取前 10 条，输出词条和热度。
4. 热度大于 10000 时换算成"万"，保留一位小数。
5. 接口失败时，调用 `web_search` 搜索"B站热搜榜"，提取当前榜单。
6. 全部失败时回复："暂时抓不到B站热搜。"

## 输出格式

```text
📺 B站热搜 Top 10

1. 热搜词条 710.7万
2. 热搜词条 221.5万
3. 热搜词条 219.1万

当前榜单主要集中在游戏、娱乐和社会话题。
```