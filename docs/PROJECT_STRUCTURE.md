# 项目结构说明

## 目录结构

```
sync-tools/
├── sync_client.py          # 客户端入口脚本
├── sync_server.py          # 服务端入口脚本
├── sync_keygen.py          # 密钥生成工具
├── setup.py                # 安装配置
├── requirements.txt        # 依赖列表
├── README.md               # 项目说明
│
├── sync_tools/             # 主包目录
│   ├── __init__.py
│   ├── core/               # 核心模块
│   │   ├── __init__.py
│   │   ├── client.py       # 客户端实现
│   │   ├── server.py       # 服务端实现
│   │   └── sync_core.py    # 同步核心逻辑
│   │
│   └── utils/              # 工具模块
│       ├── __init__.py
│       ├── config_manager.py   # 配置管理
│       ├── encryption.py       # 加密模块
│       ├── file_hasher.py      # 文件hash和版本管理
│       └── progress.py         # 进度显示
│
├── examples/               # 示例配置
│   ├── client_config.json
│   └── server_config.json
│
├── tests/                  # 测试目录
│   └── test_integration.py
│
└── docs/                   # 文档目录
    └── PROJECT_STRUCTURE.md
```

## 核心概念

### 1. 版本号系统

- **sync_version**: 服务端全局版本号，每次有变更时递增
- **base_version**: 客户端记录的基准版本，表示上次同步时的服务端版本
- **file version**: 每个文件的版本号，文件内容变化时递增

### 2. Tombstone机制

当文件被删除时，不是简单地从状态中移除，而是保留一个"墓碑"记录：

```json
{
  "path/to/deleted.txt": {
    "hash": "",
    "size": 0,
    "version": 3,
    "status": "deleted",
    "deleted_at": "2024-01-01T12:00:00"
  }
}
```

这样可以确保：
- 删除操作能够正确同步到其他客户端
- 避免删除的文件被重新同步回来

### 3. 冲突检测

冲突发生在以下情况：

1. **版本偏移**: `client_base_version < server_current_version`
2. **内容冲突**: 同一文件在客户端和服务端都有修改
3. **删除冲突**: 一方删除，另一方修改

## 同步算法

### Push模式（客户端 → 服务端）

```python
def compute_push_actions(local_state, remote_state):
    for each file:
        if local_active and not remote:
            # 本地新增 → 上传
            upload(file)
        
        elif local_deleted and remote_active:
            # 本地删除 → 删除远程
            if local_version > remote_version:
                delete_remote(file)
            else:
                conflict("本地删除了远程修改的文件")
        
        elif local_active and remote_active:
            # 两边都有
            if local_hash != remote_hash:
                if version_diverged and remote_version > local_version:
                    conflict("文件在两边都被修改")
                else:
                    upload(file)
```

### Pull模式（服务端 → 客户端）

```python
def compute_pull_actions(local_state, remote_state):
    for each file:
        if remote_active and not local:
            # 远程新增 → 下载
            download(file)
        
        elif remote_deleted and local_active:
            # 远程删除 → 删除本地
            if remote_version > local_version:
                delete_local(file)
        
        elif remote_active and local_active:
            # 两边都有
            if remote_hash != local_hash:
                if remote_version > local_version:
                    download(file)
```

## 通信协议

### 消息格式

```
+------------------+------------------+----------+----------+
| cmd_len (4bytes) | data_len (4bytes)| cmd      | data     |
+------------------+------------------+----------+----------+
```

### 命令列表

| 命令 | 描述 |
|------|------|
| HELLO | 客户端握手 |
| OK | 操作成功 |
| ERROR | 操作失败 |
| CONFLICT | 检测到冲突 |
| GET_STATE | 获取状态 |
| SYNC_REQUEST | 同步请求 |
| FILE_DATA | 文件数据 |
| DELETE_FILE | 删除文件 |
| SYNC_COMPLETE | 同步完成 |

## 状态文件

### 客户端状态 (client_sync_state.json)

```json
{
  "files": { ... },
  "sync_version": 0,
  "last_sync_time": "...",
  "client_id": "abc12345",
  "base_version": 5
}
```

- `client_id`: 唯一标识此客户端
- `base_version`: 上次同步时的服务端版本

### 服务端状态 (server_sync_state.json)

```json
{
  "files": { ... },
  "sync_version": 6,
  "last_sync_time": "...",
  "client_id": "server",
  "base_version": 0
}
```

- `sync_version`: 当前全局版本号

## 多人协作场景

### 场景1: 正常协作

```
时间线:
T1: ClientA push → version=1
T2: ClientB pull → base_version=1  
T3: ClientB push → version=2
T4: ClientA pull → base_version=2
T5: ClientA push → version=3
```

### 场景2: 同时修改（冲突）

```
T1: ClientA 上次同步 → base_version=1
T2: ClientB push → version=2 (服务端更新)
T3: ClientA 修改了文件
T4: ClientA push → 检测到冲突！
    因为: ClientA.base_version(1) < server.version(2)
    且同一文件被修改
```

解决方案：
1. ClientA 先 pull 获取 ClientB 的更改
2. 手动合并冲突文件
3. 再 push

### 场景3: 删除冲突

```
T1: ClientA 删除 file.txt
T2: ClientB 修改 file.txt, push → version=2
T3: ClientA push → 冲突！
    ClientA 想删除，但 ClientB 修改了
```
