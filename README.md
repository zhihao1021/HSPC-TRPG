# D&D 5e TRPG Discord Bot

一個以《龍與地下城》第五版(D&D 5e)為系統的 Discord TRPG Bot。它扮演**地下城主(GM)**,帶領玩家進行一場由行動驅動的開放式冒險;而這場冒險真正的目的,是在約 30 天的過程中**一組一組地逐步公布「晉級隊伍名單」**——讓原本制式的名單公布,變成一段互動式的冒險旅程。

- LLM:透過 OpenAI 相容介面串接 **Deepseek 官方 API**,支援 thinking(推理)模式。
- 資料庫:**PostgreSQL**(`asyncpg`),每個 Discord 頻道擁有獨立的 session、劇情與名單。
- GM 會靈活回應玩家的各種決策,並透過工具擲骰、管理角色、在合適時機公布名單。

---

## 運作概念

- **每個頻道是一場獨立冒險**。只有當資料庫中存在該頻道的 session(由管理員以 `/start` 建立)時,Bot 才會回應該頻道的訊息;否則一律忽略。
- 玩家直接在頻道中**發一般訊息**即為「行動」。Bot 會把訊息連同**當下時間、玩家名稱、玩家 ID**(以及解析後的 @提及)一起交給模型,生成 GM 回應。
- 結果不確定時,GM 會呼叫**擲骰工具**,擲骰結果以 Embed 自動呈現(由工具產生,確保準確)。
- 名單採**逐步、約每天一組**的節奏公布;模型被嚴格限制不得提前洩漏或過快推進。公布時會**融入劇情敘述**,並把已公布名單寫入獨立紀錄檔。

---

## 專案結構

```
.
├── main.py              進入點;解析 --env、載入設定、啟動 DB 與 Bot
├── bot.py               Discord 事件(on_message)與 slash commands、Embed 組裝
├── db.py                asyncpg 連線池與自動建表
├── config.py            集中式設定(全部來自環境變數)
├── model/               資料模型(Pydantic + SQL 存取)
│   ├── session.py       頻道 session(摘要、token 用量)
│   ├── message.py       對話訊息(user/assistant/tool)
│   ├── user.py          玩家角色(屬性/HP/技能/裝備)
│   └── roster.py        晉級名單條目
├── llm/                 LLM 相關
│   ├── client.py        Deepseek 對話生成、tool-calling 迴圈、context 壓縮
│   ├── tools.py         工具定義與執行(擲骰/查角色/更新角色/公布隊伍)
│   └── context.py       訊息組裝、動態脈絡注入、工具序列健全化
├── game/
│   └── roster.py        名單 JSON 載入、種入、公布節奏判斷、紀錄輸出
├── prompts/             模型提示(獨立存放,便於維護)
│   ├── system.md        GM 主提示(風格、節奏、安全、防注入)
│   └── summary.md       Context 壓縮(摘要)提示
├── sql/
│   └── create_tables.sql
└── data/
    ├── roster.example.json   名單格式範例
    └── revealed/<channel>.json   (執行期產生)已公布名單紀錄
```

---

## 安裝與設定

### 1. 環境

需求環境與套件已安裝於專案的 `.venv` 中(Python 3、`py-cord`、`openai`、`asyncpg`、`pydantic`、`orjson`、`pydantic-snowflake`、`python-dotenv`)。

### 2. PostgreSQL

準備一個可連線的 PostgreSQL 資料庫。建表會在啟動時自動執行(`sql/create_tables.sql`,使用 `CREATE TABLE IF NOT EXISTS`)。

### 3. 設定檔(.env)

複製範例並填入實際值:

```powershell
Copy-Item .env.example .env
```

主要設定(完整清單見下表):

- `DISCORD_BOT_TOKEN` — Discord Bot Token(需開啟 **Message Content Intent**)。
- `POSTGRES_DB_URL` — 例如 `postgresql://user:pass@host:5432/hspc_trpg`。
- `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL`。

### 4. 晉級名單

複製範例並編輯成你的名單:

```powershell
Copy-Item data/roster.example.json data/roster.json
```

名單格式:

```json
{
  "title": "第 X 屆晉級隊伍名單",
  "description": "說明文字(選填)",
  "teams": [
    { "name": "烈焰先鋒", "reveal_date": "2026-06-01" },
    { "name": "霜之守望", "reveal_date": "2026-06-02" }
  ]
}
```

- `name`:隊伍名稱(模型公布時必須與此完全相符)。
- `reveal_date`:**建議公布日期**(`YYYY-MM-DD`)。Bot 不會在該日期之前公布該隊伍;到期後由 GM 擇機在劇情中揭曉。

---

## 執行

```powershell
.venv\Scripts\python.exe main.py
```

使用其他設定檔:

```powershell
.venv\Scripts\python.exe main.py --env .env.staging
```

---

## 指令與玩法

### Slash Commands

| 指令 | 權限 | 說明 |
| --- | --- | --- |
| `/start` | 伺服器管理員 | 在目前頻道開始一場新冒險:建立 session、從 JSON 種入名單,並由 GM **自動輸出開場導言**。 |
| `/status` | 任何玩家 | 查看自己的角色(等級/HP/屬性/技能/裝備)與名單公布進度。 |

### 玩家如何遊玩

1. 管理員在某頻道執行 `/start`;GM 會先發一段開場導言,鋪陳世界觀並邀請玩家行動。
2. 玩家直接在該頻道中描述自己的行動(可 @ 其他玩家)。
3. GM(Bot)回應劇情;需要時自動擲骰並顯示結果 Embed(含 DC 門檻、成功/失敗判定與說明)。
4. 隨著冒險推進,GM 會在到期且劇情合適時,把晉級隊伍融入故事公布出來。

### 角色創建(私訊進行)

當一位**尚未建立角色**的玩家首次在遊戲頻道行動時,Bot **不會**在頻道公開回應(避免干擾進行中的遊戲),而是:

1. 為該玩家開啟一個臨時的「創角 session」(綁定其私訊頻道)。
2. **私訊**該玩家,一對一引導完成 D&D 5e 角色創建(可擲骰決定屬性)。
3. 完成後,角色會寫入對應的遊戲頻道,臨時 session 自動結束,玩家即可回到頻道開始冒險。

---

## 設定參考

| 變數 | 預設 | 說明 |
| --- | --- | --- |
| `DISCORD_BOT_TOKEN` | — | Discord Bot Token(必填)。 |
| `POSTGRES_DB_URL` | `postgresql://hspc:hspc@localhost:5432/hspc_trpg` | 資料庫連線字串。 |
| `POSTGRES_POOL_MIN_SIZE` / `POSTGRES_POOL_MAX_SIZE` | `5` / `10` | 連線池大小。 |
| `DEEPSEEK_API_KEY` | — | Deepseek API 金鑰(必填)。 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | API 端點。 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 主對話/工具呼叫使用的模型。 |
| `CONTEXT_SUMMARY_MODEL` | (沿用 `DEEPSEEK_MODEL`) | **壓縮 Context(摘要)使用的模型**;可設成較便宜的模型以省成本。 |
| `CHARGEN_MODEL` | (沿用 `DEEPSEEK_MODEL`) | **私訊創角使用的模型**;可設成不同模型。 |
| `DEEPSEEK_REASONING_ENABLED` | `true` | 啟用 thinking,嘗試讀取並(選擇性)輸出 `reasoning_content`。 |
| `DEEPSEEK_TEMPERATURE` | `1.0` | 取樣溫度。 |
| `DEEPSEEK_MAX_TOKENS` | `4096` | 單次回應最大 token。 |
| `LLM_MAX_TOOL_ITERATIONS` | `6` | 單次回應中 tool-calling 迴圈最大往返次數。 |
| `CONTEXT_WINDOW` | `1000000` | 模型 context window 總大小(token)。Deepseek v4 約 1M。 |
| `CONTEXT_TRIGGER_RATIO` | `0.75` | 當 prompt token 用量超過 `window × 此比例` 時觸發壓縮(預設 75%)。 |
| `CONTEXT_COMPRESS_RATIO` | `0.5` | **壓縮比率**:壓縮後把 context 縮減到 `window × 此比例`。 |
| `CONTEXT_KEEP_RECENT` | `40` | 壓縮時至少保留的最近訊息則數。 |
| `CONTEXT_MAX_FETCH` | `400` | 組裝請求時最多撈取的歷史訊息則數。 |
| `ROSTER_FILE` | `data/roster.json` | 晉級名單來源檔。 |
| `REVEALED_DIR` | `data/revealed` | 已公布名單紀錄輸出目錄(每頻道一份 `<channel_id>.json`)。 |
| `SHOW_REASONING` | `false` | 是否把模型 thinking 內容輸出到 Discord。 |

> 關於 thinking 模式:若使用支援推理的模型(例如 `deepseek-reasoner` 或具推理能力的版本),設定 `DEEPSEEK_MODEL` 為該模型即可;Bot 會自動讀取 `reasoning_content`。請選用**同時支援 function calling 與推理**的模型,以確保工具可正常使用。

---

## 工具(Function Calling)

| 工具 | 用途 |
| --- | --- |
| `roll_dice` | 擲骰(攻擊/檢定/豁免/隨機事件)。可附 `dc`(門檻)與 `description`(說明);結果自動以 Embed 顯示,含成功/失敗/大成功/大失敗判定。 |
| `get_character` | 依 Discord 玩家 ID 查詢角色屬性、HP、技能、裝備。 |
| `update_character` | 更新角色狀態(受傷、升級、取得物品、學會技能等)。 |
| `reveal_team` | 在到期且劇情合適時公布一組晉級隊伍;會驗證日期、寫入紀錄檔,並要求模型融入敘事。 |
| `finalize_character` | (僅私訊創角)依玩家確認的設定建立角色,寫入對應遊戲頻道。 |

> **Terminal 日誌**:每次工具呼叫的參數與結果都會輸出到終端機 log(含時間戳),例如:
> `2026-06-01 00:14:55 [INFO] trpg.tools: tool-call channel=... name=roll_dice args={...}` 與隨後的 `tool-result ... -> ...`。

---

## Context 壓縮機制

採**比率制**:當上一次請求的 prompt token 用量超過 `CONTEXT_WINDOW × CONTEXT_TRIGGER_RATIO`(預設 1M × 75% = 750k)時觸發壓縮。Bot 會:

1. 以「上次實際 token 用量」動態校準目前歷史的**字元/token 比例**。
2. 從最舊端開始挑選訊息(最近 `CONTEXT_KEEP_RECENT` 則一律保留),累積到足以把 context 縮減回 `CONTEXT_WINDOW × CONTEXT_COMPRESS_RATIO`(預設 50%)為止。
3. 用 `CONTEXT_SUMMARY_MODEL` 將這批舊訊息與既有摘要整合成新的長期劇情摘要。
4. 刪除被摘要掉的舊訊息,僅以摘要保留長期記憶。

角色狀態、已公布名單等「持久效果」另存於資料庫,不會因壓縮而遺失。

---

## 安全與防護

- **內容安全**:GM 提示限制在奇幻冒險 PG-13 範圍,拒絕露骨色情、過度血腥、現實族群仇恨/歧視與違法傷害指引。
- **防 Prompt Injection**:玩家訊息一律僅視為「角色在遊戲世界中的行動」,絕不當作對系統的指令;試圖洩漏提示、提前公布名單或跳出遊戲者,會在敘事中自然失敗。
- 模型不會主動透露系統規則或未到期的隊伍名稱。
```
