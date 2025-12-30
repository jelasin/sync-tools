#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件hash计算和版本追踪工具
支持文件版本控制、删除追踪（tombstone）和同步基准点管理
"""

import hashlib
import os
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Set, List, Any
from dataclasses import dataclass, asdict
from enum import Enum


class FileStatus(Enum):
    """文件状态枚举"""
    ACTIVE = "active"      # 正常存在的文件
    DELETED = "deleted"    # 已删除（tombstone）


@dataclass
class FileInfo:
    """文件信息数据类"""
    hash: str                    # 文件MD5 hash
    size: int                    # 文件大小
    modified: str                # 修改时间 ISO格式
    version: int                 # 版本号，每次修改递增
    status: str = "active"       # 状态: active/deleted
    deleted_at: Optional[str] = None  # 删除时间（如果是tombstone）
    
    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'FileInfo':
        return cls(
            hash=data.get('hash', ''),
            size=data.get('size', 0),
            modified=data.get('modified', ''),
            version=data.get('version', 1),
            status=data.get('status', 'active'),
            deleted_at=data.get('deleted_at')
        )


@dataclass
class SyncState:
    """同步状态数据类"""
    files: Dict[str, FileInfo]              # 所有文件状态（包括tombstone）
    sync_version: int                        # 全局同步版本号
    last_sync_time: str                      # 上次同步时间
    client_id: str                           # 客户端唯一标识
    base_version: int                        # 基于的服务器版本（用于冲突检测）
    
    def to_dict(self) -> Dict:
        return {
            'files': {k: v.to_dict() for k, v in self.files.items()},
            'sync_version': self.sync_version,
            'last_sync_time': self.last_sync_time,
            'client_id': self.client_id,
            'base_version': self.base_version
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SyncState':
        files = {}
        for k, v in data.get('files', {}).items():
            files[k] = FileInfo.from_dict(v)
        return cls(
            files=files,
            sync_version=data.get('sync_version', 0),
            last_sync_time=data.get('last_sync_time', ''),
            client_id=data.get('client_id', ''),
            base_version=data.get('base_version', 0)
        )


class FileHasher:
    """文件hash计算和版本管理类"""
    
    def __init__(self, base_dir: str, state_file: Optional[str] = None, client_id: Optional[str] = None):
        """
        初始化FileHasher
        
        Args:
            base_dir: 基础目录路径
            state_file: 保存状态的文件路径
            client_id: 客户端唯一标识
        """
        self.base_dir = Path(base_dir).resolve()
        if state_file:
            self.state_file = Path(state_file).resolve()
        else:
            self.state_file = self.base_dir / ".sync_state.json"
        
        # 生成客户端ID（如果未提供）
        self.client_id = client_id or self._generate_client_id()
        
        # 加载同步状态
        self.sync_state: SyncState = self._load_state()
    
    def _generate_client_id(self) -> str:
        """生成唯一客户端ID"""
        import uuid
        return str(uuid.uuid4())[:8]
    
    def calculate_file_hash(self, file_path: Path) -> str:
        """
        计算文件的MD5 hash值
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件的MD5 hash值
        """
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except (IOError, OSError) as e:
            print(f"计算文件hash失败: {file_path} - {e}")
            return ""
    
    def get_relative_path(self, file_path: Path) -> str:
        """
        获取相对于基础目录的路径（统一使用正斜杠）
        """
        try:
            relative_path = file_path.relative_to(self.base_dir)
            return str(relative_path).replace(os.sep, '/')
        except ValueError:
            return str(file_path).replace(os.sep, '/')
    
    def scan_directory(self) -> Dict[str, FileInfo]:
        """
        扫描目录并获取所有文件的当前状态
        
        Returns:
            包含文件信息的字典（只包含存在的文件，不包含tombstone）
        """
        current_files = {}
        
        if not self.base_dir.exists():
            print(f"目录不存在: {self.base_dir}")
            return current_files
        
        for root, dirs, files in os.walk(self.base_dir):
            root_path = Path(root)
            
            # 跳过隐藏目录
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for file_name in files:
                if file_name.startswith('.'):
                    continue
                
                file_path = root_path / file_name
                relative_path = self.get_relative_path(file_path)
                
                # 跳过状态文件本身
                if file_path == self.state_file:
                    continue
                
                file_hash = self.calculate_file_hash(file_path)
                if file_hash:
                    stat = file_path.stat()
                    # 获取已有版本号或设为1
                    existing = self.sync_state.files.get(relative_path)
                    version = existing.version if existing else 1
                    
                    current_files[relative_path] = FileInfo(
                        hash=file_hash,
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        version=version,
                        status='active'
                    )
        
        return current_files
    
    def get_local_changes(self) -> Dict[str, List[str]]:
        """
        对比当前文件系统和上次同步状态，获取本地变更
        
        Returns:
            {
                'added': [],      # 新增文件
                'modified': [],   # 修改文件
                'deleted': [],    # 删除的文件（本地存在tombstone或之前同步过现在不存在）
                'unchanged': []   # 未变化
            }
        """
        current_files = self.scan_directory()
        previous_state = self.sync_state.files
        
        changes = {
            'added': [],
            'modified': [],
            'deleted': [],
            'unchanged': []
        }
        
        # 检查当前存在的文件
        for file_path, file_info in current_files.items():
            if file_path not in previous_state:
                # 新文件
                changes['added'].append(file_path)
            elif previous_state[file_path].status == 'deleted':
                # 之前删除过，现在又存在了（恢复）
                changes['added'].append(file_path)
            elif previous_state[file_path].hash != file_info.hash:
                # 内容变化
                changes['modified'].append(file_path)
            else:
                # 未变化
                changes['unchanged'].append(file_path)
        
        # 检查删除的文件
        for file_path, file_info in previous_state.items():
            if file_info.status == 'active' and file_path not in current_files:
                # 之前存在且是活跃的，现在不存在了 = 被删除
                changes['deleted'].append(file_path)
        
        return changes
    
    def get_current_state_dict(self) -> Dict[str, Dict]:
        """
        获取当前状态的字典表示（用于网络传输）
        包括活跃文件和tombstone
        """
        current_files = self.scan_directory()
        result = {}
        
        # 添加当前存在的文件
        for path, info in current_files.items():
            # 检查是否与之前同步状态有变化
            prev = self.sync_state.files.get(path)
            if prev and prev.hash == info.hash:
                # 无变化，使用之前的版本号
                result[path] = prev.to_dict()
            else:
                # 有变化或新文件，递增版本号
                new_version = (prev.version + 1) if prev else 1
                info.version = new_version
                result[path] = info.to_dict()
        
        # 添加tombstone（删除标记）
        for path, info in self.sync_state.files.items():
            if info.status == 'deleted':
                result[path] = info.to_dict()
            elif path not in current_files and info.status == 'active':
                # 文件被删除了，创建tombstone
                tombstone = FileInfo(
                    hash='',
                    size=0,
                    modified=datetime.now().isoformat(),
                    version=info.version + 1,
                    status='deleted',
                    deleted_at=datetime.now().isoformat()
                )
                result[path] = tombstone.to_dict()
        
        return result
    
    def _load_state(self) -> SyncState:
        """加载同步状态"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    state = SyncState.from_dict(data)
                    # 确保client_id一致
                    if not state.client_id:
                        state.client_id = self.client_id
                    return state
            except (json.JSONDecodeError, IOError) as e:
                print(f"加载状态文件失败: {e}")
        
        # 返回空状态
        return SyncState(
            files={},
            sync_version=0,
            last_sync_time='',
            client_id=self.client_id,
            base_version=0
        )
    
    def save_state(self, state: Optional[SyncState] = None) -> bool:
        """保存同步状态"""
        if state:
            self.sync_state = state
        
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.sync_state.to_dict(), f, indent=2, ensure_ascii=False)
            return True
        except (IOError, OSError) as e:
            print(f"保存状态文件失败: {e}")
            return False
    
    def update_state_after_sync(self, server_version: int):
        """
        同步完成后更新本地状态
        
        Args:
            server_version: 服务器当前版本号
        """
        current_files = self.scan_directory()
        
        new_files = {}
        for path, info in current_files.items():
            new_files[path] = info
        
        # 清理过期的tombstone（可选：保留最近N天的）
        # 这里简化处理，只保留当前会话的tombstone
        
        self.sync_state = SyncState(
            files=new_files,
            sync_version=server_version,
            last_sync_time=datetime.now().isoformat(),
            client_id=self.client_id,
            base_version=server_version
        )
        self.save_state()
    
    def mark_file_deleted(self, file_path: str):
        """
        标记文件为已删除（创建tombstone）
        """
        existing = self.sync_state.files.get(file_path)
        if existing:
            tombstone = FileInfo(
                hash='',
                size=0,
                modified=datetime.now().isoformat(),
                version=existing.version + 1,
                status='deleted',
                deleted_at=datetime.now().isoformat()
            )
            self.sync_state.files[file_path] = tombstone
    
    def mark_file_synced(self, file_path: str, file_info: Dict):
        """
        标记文件已同步
        """
        self.sync_state.files[file_path] = FileInfo.from_dict(file_info)
    
    def get_file_list(self) -> Set[str]:
        """获取当前所有文件列表"""
        current_state = self.scan_directory()
        return set(current_state.keys())
    
    def get_changes(self) -> Dict[str, Dict]:
        """
        获取文件变化情况（兼容旧API）
        """
        changes = self.get_local_changes()
        current_files = self.scan_directory()
        
        result = {
            'added': {p: current_files[p].to_dict() for p in changes['added'] if p in current_files},
            'modified': {p: current_files[p].to_dict() for p in changes['modified'] if p in current_files},
            'deleted': {p: self.sync_state.files[p].to_dict() for p in changes['deleted'] if p in self.sync_state.files},
            'unchanged': {p: current_files[p].to_dict() for p in changes['unchanged'] if p in current_files}
        }
        return result
    
    def update_state(self):
        """
        更新状态到最新（兼容旧API）
        
        重要：保留删除标记（tombstone），以便其他客户端能够同步删除操作
        """
        current_files = self.scan_directory()
        
        # 保留已有的 tombstone，并为新删除的文件创建 tombstone
        new_state = {}
        
        # 添加当前存在的文件
        for path, info in current_files.items():
            new_state[path] = info
        
        # 处理之前存在但现在不存在的文件（创建或保留 tombstone）
        for path, info in self.sync_state.files.items():
            if path not in current_files:
                if info.status == 'deleted':
                    # 保留已有的 tombstone
                    new_state[path] = info
                elif info.status == 'active':
                    # 创建新的 tombstone
                    tombstone = FileInfo(
                        hash='',
                        size=0,
                        modified=datetime.now().isoformat(),
                        version=info.version + 1,
                        status='deleted',
                        deleted_at=datetime.now().isoformat()
                    )
                    new_state[path] = tombstone
        
        self.sync_state.files = new_state
        self.sync_state.last_sync_time = datetime.now().isoformat()
        self.save_state()


if __name__ == "__main__":
    # 测试代码
    hasher = FileHasher("./test_dir")
    changes = hasher.get_changes()
    print("文件变化:")
    for change_type, files in changes.items():
        if files:
            print(f"{change_type}: {list(files.keys())}")
