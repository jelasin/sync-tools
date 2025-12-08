# 文件同步工具 v2.0

这是一个功能强大的基于Python的文件同步工具，包含客户端和服务端，支持文件和目录的安全双向同步。

## ✨ 功能特性

### 核心功能

- 📁 **基于文件hash值的增量同步**
- 🔄 **支持完整目录结构同步**
- ⬆️ **客户端推送(PUSH)和拉取(PULL)模式**
- 🗑️ **正确处理文件删除同步**（v2.0新增）
- 🌐 **服务端支持多客户端并发连接**
- 💾 **使用JSON格式保存同步状态**

### 版本控制与冲突处理（v2.0新增）

- 📊 **全局版本号**：服务端维护全局版本号，每次变更递增
- 🔖 **Tombstone机制**：删除的文件保留删除记录，确保删除操作正确同步
- ⚠️ **冲突检测**：当多人同时修改时，自动检测并报告冲突
- 🔀 **多种冲突策略**：支持 ask/local/remote/skip 多种处理方式

### 安全特性

- 🔐 **AES加密传输**：使用Fernet对称加密保护文件传输
- 🔑 **自动密钥管理**：自动生成和管理加密密钥对
- ✅ **完整性校验**：传输后自动验证文件完整性
- 🛡️ **安全认证**：内置数据认证防止篡改

### 用户体验

- 📊 **实时进度条**：显示文件传输进度和速度
- ⚙️ **配置文件支持**：灵活的JSON配置管理
- 🚀 **高性能传输**：优化的分块传输，支持大文件
- 📝 **详细日志**：完整的操作日志和错误提示

### 性能优化（v2.1新增）

- 📦 **可选压缩**：自动压缩文本文件，减少传输量
- 🔄 **流式传输**：大文件流式处理，不占用大量内存
- ⚡ **大缓冲区**：64KB 块大小，提高传输效率
- 🎯 **智能模式**：根据文件大小自动选择最优传输模式

## 📋 系统要求

- Python 3.6+
- 依赖库：
  - `cryptography>=3.4.8` - 加密功能
  - `tqdm>=4.62.0` - 进度条显示

## 🚀 使用方式

### 方式一：直接运行（开发模式）

```bash
# 服务端
python sync_server.py --config examples/server_config.json

# 客户端
python sync_client.py --config examples/client_config.json --mode push

# 密钥生成
python sync_keygen.py --generate-keys
```

### 方式二：安装后使用（推荐）

```bash
# 安装包
pip install -e .

# 使用命令行工具
sync-server --config examples/server_config.json
sync-client --config examples/client_config.json --mode push
sync-keygen --generate-keys
```

### 方式三：作为Python包导入

```python
from sync_tools.core.server import SyncServer
from sync_tools.core.client import SyncClient
from sync_tools.utils.encryption import EncryptionManager

# 在代码中使用
server = SyncServer(config_file="server_config.json")
client = SyncClient(config_file="client_config.json")
```

## 🔄 同步流程

### Push（推送）模式

```
客户端                                   服务端
   |                                       |
   |------- 1. 连接握手 (HELLO) -------->  |
   |<------ 2. 确认连接 (OK) --------------|
   |                                       |
   |------- 3. 同步请求 (SYNC_REQUEST) ->  |
   |        [本地状态, 基准版本]           |
   |                                       |
   |        4. 检查版本冲突                |
   |        5. 计算同步计划                |
   |                                       |
   |<------ 6. 同步计划 (OK) --------------|
   |        或 冲突提示 (CONFLICT)         |
   |                                       |
   |------- 7. 上传文件 (FILE_DATA) ---->  |
   |------- 8. 删除请求 (DELETE_FILE) -->  |
   |                                       |
   |------- 9. 同步完成 (SYNC_COMPLETE) -> |
   |<------ 10. 新版本号 (OK) -------------|
   |                                       |
```

### Pull（拉取）模式

```
客户端                                   服务端
   |                                       |
   |------- 1. 连接握手 (HELLO) -------->  |
   |<------ 2. 确认连接 (OK) --------------|
   |                                       |
   |------- 3. 同步请求 (SYNC_REQUEST) ->  |
   |        [本地状态]                     |
   |                                       |
   |        4. 计算同步计划                |
   |                                       |
   |<------ 5. 同步计划 (OK) --------------|
   |        [需下载文件, 需删除文件]       |
   |                                       |
   |<------ 6. 发送文件 (FILE_DATA) -------|
   |                                       |
   |        7. 删除本地文件                |
   |        8. 更新本地状态                |
   |                                       |
```

## ⚠️ 冲突处理

### 什么情况会产生冲突？

1. **同时修改**：客户端A和客户端B同时修改了同一个文件
2. **删除与修改冲突**：客户端A删除了文件，客户端B修改了同一个文件
3. **版本偏移**：在您上次同步后，有其他人推送了更改

### 冲突处理策略

在配置文件中设置 `conflict_strategy`：

- `ask`：提示用户手动解决（默认）
- `local`：强制使用本地版本
- `remote`：强制使用远程版本  
- `skip`：跳过冲突文件

### 建议的工作流程

1. **推送前先拉取**：`sync-client --mode pull`
2. **解决本地冲突**：手动处理冲突文件
3. **再推送**：`sync-client --mode push`

## 📦 模块说明

### 核心模块 (sync_tools.core)

- **sync_core.py**: 实现同步协议、冲突检测和文件传输逻辑
- **server.py**: 服务端实现，版本管理和多客户端处理
- **client.py**: 客户端实现，push/pull操作

### 工具模块 (sync_tools.utils)

- **file_hasher.py**: 文件MD5计算、版本追踪和tombstone管理
- **encryption.py**: Fernet加密/解密功能
- **progress.py**: 进度条显示组件
- **config_manager.py**: JSON配置文件管理

## 📊 状态文件格式

同步状态保存在 `sync_state.json` 中：

```json
{
  "files": {
    "path/to/file.txt": {
      "hash": "md5hash...",
      "size": 1234,
      "modified": "2024-01-01T12:00:00",
      "version": 3,
      "status": "active"
    },
    "deleted/file.txt": {
      "hash": "",
      "size": 0,
      "modified": "2024-01-02T12:00:00",
      "version": 2,
      "status": "deleted",
      "deleted_at": "2024-01-02T12:00:00"
    }
  },
  "sync_version": 5,
  "last_sync_time": "2024-01-02T12:00:00",
  "client_id": "abc12345",
  "base_version": 4
}
```

## 🔧 客户端命令

```bash
# 查看本地文件
sync-client --mode list

# 查看文件变化
sync-client --mode changes

# 查看同步状态
sync-client --mode status

# 推送到服务端
sync-client --mode push

# 从服务端拉取
sync-client --mode pull

# 指定冲突处理策略
sync-client --mode push --conflict skip
```

## ⚡ 性能优化

### 传输优化

| 优化项 | 说明 | 效果 |
|--------|------|------|
| **大缓冲区** | 64KB 块大小 | 减少系统调用，提高吞吐量 |
| **压缩传输** | zlib 压缩文本文件 | 文本文件减少 50-90% 传输量 |
| **流式传输** | 大文件边读边传 | 不占用大量内存 |
| **智能模式** | 自动选择传输模式 | 小文件整块，大文件流式 |

### 性能数据参考

```
1MB 文件（加密+压缩）：~3 MB/s
1MB 文件（无加密）：~10+ MB/s
```

### 配置选项

```json
{
  "sync": {
    "compression": true,     // 启用压缩（推荐）
    "chunk_size": 65536      // 64KB 块大小
  }
}
```

### 大文件建议

对于超过 10MB 的大文件：
- 如不需加密，关闭 `encryption.enabled` 可显著提高速度
- 压缩对二进制文件（图片、视频）效果有限

## 🔧 开发和测试

```bash
# 运行集成测试
python tests/test_integration.py

# 检查测试结果
ls tests/test/
```

## 📝 更新日志

### v2.1.0

- ✅ 优化文件传输性能
- ✅ 添加可选压缩功能
- ✅ 支持流式传输大文件
- ✅ 增大传输缓冲区（8KB → 64KB）
- ✅ 智能选择传输模式

### v2.0.0

- ✅ 修复文件删除不同步的问题
- ✅ 添加版本控制机制
- ✅ 添加Tombstone机制追踪删除操作
- ✅ 添加多人协作冲突检测
- ✅ 添加冲突处理策略配置
- ✅ 改进状态管理和错误处理

### v1.0.0

- 基础文件同步功能
- 加密传输
- 进度显示
