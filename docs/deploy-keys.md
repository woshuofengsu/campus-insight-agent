# 密钥管理与轮换说明（deploy-keys）

本项目使用环境变量注入密钥，**严禁把密钥源码入库或提交 `.env`**（`.gitignore` 已含 `.env`/`.env.bak`）。
本文件说明各密钥的来源、生成方式、注入方式、轮换步骤与泄露处置。

---

## 1. 密钥清单

| 密钥 | 读取位置 | 用途 | 是否必需 |
|---|---|---|---|
| `WEB_JWT_SECRET` | `api_routes/deps.py::_load_secret` | JWT（HS256）签名，登录凭证防伪造 | 生产必需；演示缺省有兜底（仅演示） |
| `CRYPTO_KEY` | `utils/crypto.py::Crypto` | 敏感字段加密（手机号等），scrypt 派生密钥 | 生产必需；演示缺省有兜底（仅演示） |
| `DEEPSEEK_API_KEY` | `config.py::_secret` | LLM（DeepSeek）真实调用 | 需 LLM 时必需 |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | `config.py::_secret` | LLM 地址与模型 | 可选，有默认值 |
| `SMTP_USER` / `SMTP_PASS` / `SMTP_TO` | `config.py::_secret` | 邮件通知 | 需邮件通知时必需 |
| `HEFENG_API_KEY` / `HEFENG_API_HOST` | `config.py::_secret` | 天气真实 API（和风） | 需真实天气时必需 |
| `DEMO_MODE` | `config.py::_secret` | 演示与生产开关 | 缺省 `true` |

> **启动保护**：生产（`DEMO_MODE=false`）且未配置 `WEB_JWT_SECRET` 时，`api_routes/deps.py` 会**拒绝启动**（抛 RuntimeError），防止用兜底密钥上线。
> `CRYPTO_KEY` 未配置时 `utils/crypto.py` 会打日志并使用演示默认值——生产必须显式配置。

---

## 2. 密钥生成

### 2.1 JWT 密钥（`WEB_JWT_SECRET`）

任意长随机字符串即可。生成：

```powershell
# Windows PowerShell
$env:WEB_JWT_SECRET = [System.Convert]::ToBase64String([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
```

```bash
# Linux / mac
openssl rand -base64 32
```

### 2.2 加密密钥（`CRYPTO_KEY`）

`utils/crypto.py::Crypto` 用 scrypt 对该字符串派生 32 字节密钥。任一路径均可：

```powershell
python -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

---

## 3. 注入方式

三选一（按部署形态）：

1. **`.env` 文件**（本地/演示）：项目根目录创建 `.env`，格式 `KEY=value`，由 `utils/env_loader` 或启动脚本加载。**`.env` 已被 gitignore，绝不提交。**
2. **环境变量**（容器/PaaS）：docker `-e`、Compose `environment:`、K8s Secret 挂载。
3. **Streamlit Cloud Secrets**（Streamlit 部署）：`.streamlit/secrets.toml`，`config.py::_secret` 会先读 `st.secrets` 再回退 `os.getenv`。

---

## 4. 轮换步骤（含双写过渡，避免服务中断）

以 `CRYPTO_KEY` 为例（其余密钥同流程；`DEEPSEEK_API_KEY`/`SMTP_PASS` 轮换只需改值并用新 key 验证一次调用）：

1. **备份**：先备份数据库（含密文）。`*.db` 已在 gitignore。
2. **生成新密钥**：`python -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())"`。
3. **确认当前解密可用**：运行 `scripts/migrate_issue_phone_encryption.py --rollback`（用旧 key）验证可完整解密 → 再 `migrate()` 回密文，确认旧 key 工作正常。
4. **切换到新密钥**：把 `CRYPTO_KEY` 更新为新值。
5. **全量重加密**（旧密文用新 key 解不开，需先回滚明文再重加密）：
   ```bash
   # 用旧 key 回滚明文（此时环境仍持旧 key）
   python scripts/migrate_issue_phone_encryption.py --rollback
   # 用新 key 重新加密
   python scripts/migrate_issue_phone_encryption.py
   ```
   > 注意：回滚/重加密前后必须**保持环境变量的 CRYPTO_KEY 与操作一致**。先在旧 key 下回滚，切换 key 后再加密。
6. **清理留痕**：迁移脚本幂等，可重复执行；确认 `SELECT COUNT(*) FROM community_issues WHERE reporter_phone != ''` 为 0（无明文）。

**`WEB_JWT_SECRET` 轮换**：改值即生效（每次请求重新校验）。**所有已登录用户会立即失效**，需重新登录。建议在低峰期操作，并通知用户重新登录。

---

## 5. 泄露处置

| 泄漏项 | 立即处置 |
|---|---|
| `WEB_JWT_SECRET` | ① 立即轮换密钥；② 通知全部用户重新登录；③ 用 `trace_id`（schema v37）对可疑 `activity_log`/`agent_logs` 追溯；④ 若 token 被截图传输，检查是否 `Authorization` 头泄漏。 |
| `CRYPTO_KEY` | ① 立即换钥并走第 4 节全量重加密；② 对已泄漏窗口内的手机号排查是否被明文读取（`phone` 列应为空）。 |
| `DEEPSEEK_API_KEY` / `SMTP_PASS` | ① 到对应平台重置；② 查 API 用量异常。 |
| `.env` 文件被提交 | ① 立即从 git 历史清除（建议用 BFG/filter-repo）；② **轮换所有含密钥**；③ 确认 `.gitignore` 有 `.env`/`.env.bak`。 |

---

## 6. 检查清单（部署前自查）

- [ ] `.env` / `.env.bak` / `*.db` / `uploads/` / `nginx/certs/` 均在 `.gitignore`，无提交记录。
- [ ] `git grep -i "WEB_JWT_SECRET\|CRYPTO_KEY\|DEEPSEEK_API_KEY\|SMTP_PASS"` 在源码中只剩环境变量读取，无硬编码真实值。
- [ ] `DEMO_MODE=false` 时启动不报错（说明 `WEB_JWT_SECRET` 已配置）。
- [ ] 数据表无明文手机号：`SELECT COUNT(*) FROM community_issues WHERE reporter_phone != ''` = 0；`user_profile.phone`、`emergency_contacts.phone` = 空。
- [ ] 生产用 `AES-256-GCM`（见 `utils/crypto.py` 注释），非 stdlib 演示实现。
