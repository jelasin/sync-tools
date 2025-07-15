# 项目结构说明

## 📁 目录结构

```text
sync-tools/
├── sync_tools/                 # 主要源码包
│   ├── __init__.py             # 包初始化文件
│   ├── core/                   # 核心功能模块
│   │   ├── __init__.py
│   │   ├── sync_core.py        # 同步核心逻辑
│   │   ├── server.py           # 服务端实现
│   │   └── client.py           # 客户端实现
│   └── utils/                  # 工具模块
│       ├── __init__.py
│       ├── file_hasher.py      # 文件哈希计算
│       ├── encryption.py       # 加密功能
│       ├── progress.py         # 进度条显示
│       └── config_manager.py   # 配置管理
├── examples/                   # 示例配置文件
│   ├── server_config.json      # 服务端配置示例
│   └── client_config.json      # 客户端配置示例
├── tests/                      # 测试文件
│   ├── test_integration.py     # 集成测试
│   └── test/                   # 测试数据目录
├── docs/                       # 文档
│   └── USAGE.md                # 详细使用指南
├── server.py                   # 兼容性：旧版服务端入口
├── client.py                   # 兼容性：旧版客户端入口
├── sync_server.py              # 新版服务端入口
├── sync_client.py              # 新版客户端入口
├── sync_keygen.py              # 密钥生成工具入口
├── setup.py                    # 安装脚本
├── requirements.txt            # 依赖包列表
├── README.md                   # 项目说明
├── LICENSE                     # 许可证
└── .gitignore                  # Git忽略规则
```

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

## 📋 兼容性说明

为了向后兼容，保留了原来的 `server.py` 和 `client.py` 入口文件。新的项目结构提供了更好的模块化和可维护性。
