# 文件同步工具

这是一个功能强大的基于Python的文件同步工具，包含客户端和服务端，支持文件和目录的安全双向同步。

## ✨ 功能特性

### 核心功能

- 📁 基于文件hash值的增量同步
- 🔄 支持完整目录结构同步
- ⬆️ 客户端推送(PUSH)和拉取(PULL)模式
- 🌐 服务端支持多客户端并发连接
- 💾 使用JSON格式保存同步状态

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

## 📦 模块说明

### 核心模块 (sync_tools.core)

- **sync_core.py**: 实现同步协议和文件传输逻辑
- **server.py**: 服务端实现，监听客户端连接
- **client.py**: 客户端实现，连接服务端进行同步

### 工具模块 (sync_tools.utils)

- **file_hasher.py**: 文件MD5计算和状态管理
- **encryption.py**: Fernet加密/解密功能
- **progress.py**: 进度条显示组件
- **config_manager.py**: JSON配置文件管理

## 🔧 开发和测试

```bash
# 运行集成测试
python tests/test_integration.py

# 检查测试结果
ls tests/test/
```
