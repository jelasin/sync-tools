#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步核心逻辑模块
处理文件传输、同步协议和冲突检测

优化特性:
1. 流式传输 - 大文件不需要完全加载到内存
2. 大缓冲区 - 64KB 块提高传输效率
3. 可选压缩 - 减少传输数据量
4. 分块加密 - 提高加密传输效率
"""

import json
import socket
import struct
import os
import zlib
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Generator
from dataclasses import dataclass
from enum import Enum

from sync_tools.utils.file_hasher import FileHasher, FileInfo, SyncState

try:
    from sync_tools.utils.encryption import EncryptionManager, CRYPTO_AVAILABLE
except ImportError:
    CRYPTO_AVAILABLE = False
    EncryptionManager = None

try:
    from sync_tools.utils.progress import ProgressCallback, FileTransferProgress
except ImportError:
    ProgressCallback = None
    FileTransferProgress = None


# 传输配置
CHUNK_SIZE = 64 * 1024       # 64KB 块大小，提高传输效率
LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB 以上为大文件
COMPRESSION_THRESHOLD = 1024  # 1KB 以上启用压缩


def normalize_path(path: str) -> str:
    """标准化路径分隔符，统一使用正斜杠"""
    return path.replace(os.sep, '/').replace('\\', '/')


class SyncAction(Enum):
    """同步动作类型"""
    UPLOAD = "upload"
    DOWNLOAD = "download"
    DELETE_LOCAL = "delete_local"
    DELETE_REMOTE = "delete_remote"
    CONFLICT = "conflict"


@dataclass
class SyncItem:
    """同步项"""
    path: str
    action: SyncAction
    local_version: int
    remote_version: int
    local_hash: str
    remote_hash: str
    conflict_reason: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'path': self.path,
            'action': self.action.value,
            'local_version': self.local_version,
            'remote_version': self.remote_version,
            'local_hash': self.local_hash,
            'remote_hash': self.remote_hash,
            'conflict_reason': self.conflict_reason
        }


class SyncProtocol:
    """同步协议类"""
    
    # 协议命令
    CMD_HELLO = "HELLO"
    CMD_GET_STATE = "GET_STATE" 
    CMD_SYNC_REQUEST = "SYNC_REQUEST"
    CMD_FILE_DATA = "FILE_DATA"
    CMD_FILE_CHUNK = "FILE_CHUNK"  # 新增：文件数据块
    CMD_FILE_END = "FILE_END"      # 新增：文件传输结束
    CMD_DELETE_FILE = "DELETE_FILE"
    CMD_CREATE_DIR = "CREATE_DIR"
    CMD_SYNC_COMPLETE = "SYNC_COMPLETE"
    CMD_ERROR = "ERROR"
    CMD_OK = "OK"
    CMD_CONFLICT = "CONFLICT"
    CMD_VERSION_CHECK = "VERSION_CHECK"
    
    @staticmethod
    def pack_message(command: str, data: bytes = b"") -> bytes:
        """打包消息"""
        cmd_bytes = command.encode('utf-8')
        cmd_len = len(cmd_bytes)
        data_len = len(data)
        header = struct.pack('!II', cmd_len, data_len)
        return header + cmd_bytes + data
    
    @staticmethod
    def unpack_message(sock: socket.socket) -> Tuple[str, bytes]:
        """解包消息"""
        header = SyncProtocol._recv_exact(sock, 8)
        if not header:
            raise ConnectionError("连接已断开")
        
        cmd_len, data_len = struct.unpack('!II', header)
        
        cmd_bytes = SyncProtocol._recv_exact(sock, cmd_len)
        if not cmd_bytes:
            raise ConnectionError("读取命令失败")
        
        command = cmd_bytes.decode('utf-8')
        
        data = b""
        if data_len > 0:
            data = SyncProtocol._recv_exact(sock, data_len)
            if not data:
                raise ConnectionError("读取数据失败")
        
        return command, data
    
    @staticmethod
    def _recv_exact(sock: socket.socket, length: int) -> bytes:
        """精确接收指定长度的数据"""
        data = b""
        while len(data) < length:
            chunk = sock.recv(min(length - len(data), CHUNK_SIZE))
            if not chunk:
                break
            data += chunk
        return data
    
    @staticmethod
    def send_raw_data(sock: socket.socket, data: bytes) -> int:
        """发送原始数据，返回发送的字节数"""
        total_sent = 0
        while total_sent < len(data):
            sent = sock.send(data[total_sent:total_sent + CHUNK_SIZE])
            if sent == 0:
                raise ConnectionError("连接已断开")
            total_sent += sent
        return total_sent


class StreamTransfer:
    """流式文件传输器 - 优化大文件传输"""
    
    def __init__(self, encryption_manager=None, enable_compression: bool = True):
        self.encryption_manager = encryption_manager
        self.enable_compression = enable_compression
    
    def read_file_chunks(self, file_path: Path, chunk_size: int = CHUNK_SIZE) -> Generator[bytes, None, None]:
        """生成器：逐块读取文件"""
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    
    def compress_data(self, data: bytes) -> Tuple[bytes, bool]:
        """压缩数据，返回 (数据, 是否压缩)"""
        if not self.enable_compression or len(data) < COMPRESSION_THRESHOLD:
            return data, False
        
        compressed = zlib.compress(data, level=6)
        # 只有压缩后更小才使用压缩
        if len(compressed) < len(data) * 0.9:
            return compressed, True
        return data, False
    
    def decompress_data(self, data: bytes) -> bytes:
        """解压数据"""
        return zlib.decompress(data)
    
    def calculate_file_hash_streaming(self, file_path: Path) -> str:
        """流式计算文件hash，避免大文件内存问题"""
        hash_md5 = hashlib.md5()
        for chunk in self.read_file_chunks(file_path):
            hash_md5.update(chunk)
        return hash_md5.hexdigest()


class SyncPlanner:
    """同步计划生成器 - 核心同步算法"""
    
    @staticmethod
    def compute_sync_plan(
        local_state: Dict[str, Dict],
        remote_state: Dict[str, Dict],
        local_base_version: int,
        remote_current_version: int,
        mode: str = 'push'
    ) -> Tuple[List[SyncItem], bool]:
        """计算同步计划"""
        sync_items = []
        has_conflict = False
        
        version_diverged = local_base_version < remote_current_version
        all_paths = set(local_state.keys()) | set(remote_state.keys())
        
        for path in all_paths:
            local_info = local_state.get(path)
            remote_info = remote_state.get(path)
            
            local_version = local_info.get('version', 0) if local_info else 0
            remote_version = remote_info.get('version', 0) if remote_info else 0
            local_status = local_info.get('status', 'active') if local_info else None
            remote_status = remote_info.get('status', 'active') if remote_info else None
            local_hash = local_info.get('hash', '') if local_info else ''
            remote_hash = remote_info.get('hash', '') if remote_info else ''
            
            item = SyncItem(
                path=path,
                action=SyncAction.UPLOAD,
                local_version=local_version,
                remote_version=remote_version,
                local_hash=local_hash,
                remote_hash=remote_hash
            )
            
            if mode == 'push':
                action = SyncPlanner._compute_push_action(
                    local_info, remote_info, 
                    local_status, remote_status,
                    local_hash, remote_hash,
                    local_version, remote_version,
                    version_diverged
                )
            else:
                action = SyncPlanner._compute_pull_action(
                    local_info, remote_info,
                    local_status, remote_status,
                    local_hash, remote_hash,
                    local_version, remote_version
                )
            
            if action:
                item.action = action[0]
                item.conflict_reason = action[1] if len(action) > 1 else None
                
                if item.action == SyncAction.CONFLICT:
                    has_conflict = True
                
                sync_items.append(item)
        
        return sync_items, has_conflict
    
    @staticmethod
    def _compute_push_action(
        local_info, remote_info,
        local_status, remote_status,
        local_hash, remote_hash,
        local_version, remote_version,
        version_diverged
    ) -> Optional[Tuple[SyncAction, Optional[str]]]:
        """计算Push模式下的动作"""
        
        if local_info and not remote_info:
            if local_status == 'active':
                return (SyncAction.UPLOAD, None)
            else:
                return None
        
        if not local_info and remote_info:
            if remote_status == 'active':
                if version_diverged:
                    return (SyncAction.CONFLICT, "远程有新文件，但本地未同步")
                return None
            else:
                return None
        
        if local_info and remote_info:
            if local_status == 'active' and remote_status == 'active':
                if local_hash == remote_hash:
                    return None
                else:
                    if version_diverged and remote_version > local_version:
                        return (SyncAction.CONFLICT, "文件在本地和远程都被修改")
                    else:
                        return (SyncAction.UPLOAD, None)
            
            elif local_status == 'active' and remote_status == 'deleted':
                if local_version > remote_version:
                    return (SyncAction.UPLOAD, None)
                else:
                    return (SyncAction.CONFLICT, "本地修改了远程删除的文件")
            
            elif local_status == 'deleted' and remote_status == 'active':
                if local_version > remote_version:
                    return (SyncAction.DELETE_REMOTE, None)
                else:
                    if version_diverged:
                        return (SyncAction.CONFLICT, "本地删除了远程修改的文件")
                    return (SyncAction.DELETE_REMOTE, None)
            
            else:
                return None
        
        return None
    
    @staticmethod
    def _compute_pull_action(
        local_info, remote_info,
        local_status, remote_status,
        local_hash, remote_hash,
        local_version, remote_version
    ) -> Optional[Tuple[SyncAction, Optional[str]]]:
        """
        计算Pull模式下的动作
        
        Pull模式下，远端是权威源：
        - 远端有新文件 → 下载
        - 远端文件内容不同 → 下载（远端优先）
        - 远端文件已删除 → 删除本地
        """
        
        # 远端有，本地没有 → 下载
        if remote_info and not local_info:
            if remote_status == 'active':
                return (SyncAction.DOWNLOAD, None)
            else:
                return None
        
        # 远端没有，本地有 → 保持不变（Pull不会删除远端没有的本地文件）
        if not remote_info and local_info:
            return None
        
        # 两边都有
        if local_info and remote_info:
            # 本地活跃，远端活跃
            if local_status == 'active' and remote_status == 'active':
                if local_hash == remote_hash:
                    # hash相同，无需操作
                    return None
                else:
                    # hash不同，Pull模式下直接下载远端版本（远端优先）
                    return (SyncAction.DOWNLOAD, None)
            
            # 本地删除，远端活跃 → 下载远端版本（恢复文件）
            elif local_status == 'deleted' and remote_status == 'active':
                return (SyncAction.DOWNLOAD, None)
            
            # 本地活跃，远端删除 → 删除本地（远端优先）
            elif local_status == 'active' and remote_status == 'deleted':
                return (SyncAction.DELETE_LOCAL, None)
            
            # 两边都删除 → 无需操作
            else:
                return None
        
        return None


class SyncCore:
    """同步核心类 - 优化版"""
    
    def __init__(self, base_dir: str, sync_json: Optional[str] = None, 
                 encryption_manager: Optional[Any] = None,
                 progress_manager: Optional[Any] = None,
                 enable_compression: bool = True):
        """
        初始化同步核心
        
        Args:
            base_dir: 基础目录
            sync_json: 同步状态文件路径
            encryption_manager: 加密管理器
            progress_manager: 进度管理器
            enable_compression: 是否启用压缩
        """
        self.base_dir = Path(base_dir).resolve()
        self.hasher = FileHasher(str(self.base_dir), sync_json)
        self.encryption_manager = encryption_manager
        self.progress_manager = progress_manager
        self.enable_compression = enable_compression
        self.stream_transfer = StreamTransfer(encryption_manager, enable_compression)
    
    def prepare_sync_data(self, file_list: Optional[List[str]] = None) -> Dict:
        """准备同步数据（包括活跃文件和tombstone）"""
        return self.hasher.get_current_state_dict()
    
    def get_base_version(self) -> int:
        """获取本地基于的远程版本号"""
        return self.hasher.sync_state.base_version
    
    def get_sync_version(self) -> int:
        """获取当前同步版本号"""
        return self.hasher.sync_state.sync_version
    
    def compute_sync_plan(
        self, 
        remote_state: Dict[str, Dict],
        remote_version: int,
        mode: str = 'push'
    ) -> Tuple[List[SyncItem], bool]:
        """计算同步计划"""
        local_state = self.prepare_sync_data()
        local_base_version = self.get_base_version()
        
        return SyncPlanner.compute_sync_plan(
            local_state, remote_state,
            local_base_version, remote_version,
            mode
        )
    
    def send_file(self, sock: socket.socket, file_path: str) -> bool:
        """
        发送文件 - 优化版
        
        优化点:
        1. 大文件流式传输
        2. 可选压缩
        3. 更大的缓冲区
        """
        normalized_path = normalize_path(file_path)
        full_path = self.base_dir / file_path
        
        if not full_path.exists() or not full_path.is_file():
            print(f"文件不存在: {full_path}")
            return False
        
        try:
            file_size = full_path.stat().st_size
            file_hash = self.stream_transfer.calculate_file_hash_streaming(full_path)
            
            # 获取文件版本信息
            file_info_obj = self.hasher.sync_state.files.get(normalized_path)
            version = file_info_obj.version if file_info_obj else 1
            
            # 决定是否使用流式传输
            use_streaming = file_size > LARGE_FILE_THRESHOLD
            
            if use_streaming and not self.encryption_manager:
                # 大文件 + 无加密 = 流式传输
                return self._send_file_streaming(
                    sock, full_path, normalized_path, 
                    file_size, file_hash, version
                )
            else:
                # 小文件或有加密 = 整块传输
                return self._send_file_whole(
                    sock, full_path, normalized_path,
                    file_size, file_hash, version
                )
            
        except Exception as e:
            print(f"发送文件失败 {file_path}: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _send_file_whole(
        self, sock: socket.socket, full_path: Path, 
        normalized_path: str, file_size: int, 
        file_hash: str, version: int
    ) -> bool:
        """整块发送文件（适用于小文件或加密传输）"""
        try:
            # 读取文件内容
            with open(full_path, 'rb') as f:
                file_data = f.read()
            
            # 压缩
            compressed = False
            if self.enable_compression and file_size > COMPRESSION_THRESHOLD:
                compressed_data, compressed = self.stream_transfer.compress_data(file_data)
                if compressed:
                    file_data = compressed_data
            
            # 加密
            if self.encryption_manager:
                file_data = self.encryption_manager.encrypt_data(file_data)
            
            # 发送文件信息
            file_info = {
                'path': normalized_path,
                'size': file_size,
                'hash': file_hash,
                'version': version,
                'encrypted': self.encryption_manager is not None,
                'compressed': compressed,
                'transfer_size': len(file_data),
                'modified': datetime.fromtimestamp(full_path.stat().st_mtime).isoformat()
            }
            
            info_data = json.dumps(file_info).encode('utf-8')
            msg = SyncProtocol.pack_message(SyncProtocol.CMD_FILE_DATA, info_data)
            sock.sendall(msg)
            
            # 等待确认
            cmd, _ = SyncProtocol.unpack_message(sock)
            if cmd != SyncProtocol.CMD_OK:
                print(f"服务端拒绝接收文件: {normalized_path}")
                return False
            
            # 进度回调
            progress_callback = None
            if self.progress_manager and ProgressCallback:
                progress_callback = ProgressCallback(self.progress_manager, "发送")
                progress_callback.start(len(file_data), normalized_path)
            
            # 分块发送
            bytes_sent = 0
            for i in range(0, len(file_data), CHUNK_SIZE):
                chunk = file_data[i:i + CHUNK_SIZE]
                sock.sendall(chunk)
                bytes_sent += len(chunk)
                
                if progress_callback:
                    progress_callback.update(len(chunk))
            
            if progress_callback:
                progress_callback.finish(True)
            
            compression_info = " (压缩)" if compressed else ""
            encryption_info = " (加密)" if self.encryption_manager else ""
            print(f"文件发送成功: {normalized_path} ({bytes_sent:,} 字节{compression_info}{encryption_info})")
            return True
            
        except Exception as e:
            print(f"发送文件失败: {e}")
            return False
    
    def _send_file_streaming(
        self, sock: socket.socket, full_path: Path,
        normalized_path: str, file_size: int,
        file_hash: str, version: int
    ) -> bool:
        """流式发送文件（适用于大文件无加密传输）"""
        try:
            # 发送文件信息
            file_info = {
                'path': normalized_path,
                'size': file_size,
                'hash': file_hash,
                'version': version,
                'encrypted': False,
                'compressed': False,
                'transfer_size': file_size,
                'streaming': True,
                'modified': datetime.fromtimestamp(full_path.stat().st_mtime).isoformat()
            }
            
            info_data = json.dumps(file_info).encode('utf-8')
            msg = SyncProtocol.pack_message(SyncProtocol.CMD_FILE_DATA, info_data)
            sock.sendall(msg)
            
            # 等待确认
            cmd, _ = SyncProtocol.unpack_message(sock)
            if cmd != SyncProtocol.CMD_OK:
                print(f"服务端拒绝接收文件: {normalized_path}")
                return False
            
            # 进度回调
            progress_callback = None
            if self.progress_manager and ProgressCallback:
                progress_callback = ProgressCallback(self.progress_manager, "发送")
                progress_callback.start(file_size, normalized_path)
            
            # 流式发送
            bytes_sent = 0
            for chunk in self.stream_transfer.read_file_chunks(full_path, CHUNK_SIZE):
                sock.sendall(chunk)
                bytes_sent += len(chunk)
                
                if progress_callback:
                    progress_callback.update(len(chunk))
            
            if progress_callback:
                progress_callback.finish(True)
            
            print(f"文件发送成功(流式): {normalized_path} ({bytes_sent:,} 字节)")
            return True
            
        except Exception as e:
            print(f"流式发送文件失败: {e}")
            return False
    
    def receive_file(self, sock: socket.socket, file_info: Dict) -> bool:
        """
        接收文件 - 优化版
        """
        file_path = file_info['path']
        file_size = file_info['size']
        expected_hash = file_info['hash']
        is_encrypted = file_info.get('encrypted', False)
        is_compressed = file_info.get('compressed', False)
        transfer_size = file_info.get('transfer_size', file_size)
        is_streaming = file_info.get('streaming', False)
        
        normalized_path = normalize_path(file_path)
        local_file_path = normalized_path.replace('/', os.sep)
        full_path = self.base_dir / local_file_path
        
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 发送确认
            msg = SyncProtocol.pack_message(SyncProtocol.CMD_OK)
            sock.sendall(msg)
            
            # 进度回调
            progress_callback = None
            if self.progress_manager and ProgressCallback:
                progress_callback = ProgressCallback(self.progress_manager, "接收")
                progress_callback.start(transfer_size, file_path)
            
            if is_streaming:
                # 流式接收到文件
                success = self._receive_file_streaming(
                    sock, full_path, transfer_size, progress_callback
                )
            else:
                # 接收到内存
                success = self._receive_file_to_memory(
                    sock, full_path, transfer_size, 
                    is_encrypted, is_compressed, progress_callback
                )
            
            if not success:
                return False
            
            # 验证hash
            actual_hash = self.stream_transfer.calculate_file_hash_streaming(full_path)
            if actual_hash != expected_hash:
                print(f"文件hash校验失败: {file_path}")
                print(f"  期望: {expected_hash}")
                print(f"  实际: {actual_hash}")
                full_path.unlink()
                return False
            
            if progress_callback:
                progress_callback.finish(True)
            
            # 更新本地状态
            self.hasher.mark_file_synced(normalized_path, file_info)
            
            compression_info = " (压缩)" if is_compressed else ""
            encryption_info = " (加密)" if is_encrypted else ""
            streaming_info = " (流式)" if is_streaming else ""
            print(f"文件接收成功: {file_path}{compression_info}{encryption_info}{streaming_info}")
            return True
            
        except Exception as e:
            print(f"接收文件失败 {file_path}: {e}")
            if full_path.exists():
                full_path.unlink()
            return False
    
    def _receive_file_streaming(
        self, sock: socket.socket, full_path: Path,
        transfer_size: int, progress_callback
    ) -> bool:
        """流式接收文件到磁盘"""
        try:
            received_size = 0
            with open(full_path, 'wb') as f:
                while received_size < transfer_size:
                    remaining = transfer_size - received_size
                    chunk_size = min(CHUNK_SIZE, remaining)
                    chunk = sock.recv(chunk_size)
                    
                    if not chunk:
                        raise ConnectionError("连接意外断开")
                    
                    f.write(chunk)
                    received_size += len(chunk)
                    
                    if progress_callback:
                        progress_callback.update(len(chunk))
            
            return True
        except Exception as e:
            print(f"流式接收失败: {e}")
            return False
    
    def _receive_file_to_memory(
        self, sock: socket.socket, full_path: Path,
        transfer_size: int, is_encrypted: bool,
        is_compressed: bool, progress_callback
    ) -> bool:
        """接收文件到内存（适用于加密/压缩）"""
        try:
            received_size = 0
            received_data = bytearray()
            
            while received_size < transfer_size:
                remaining = transfer_size - received_size
                chunk_size = min(CHUNK_SIZE, remaining)
                chunk = sock.recv(chunk_size)
                
                if not chunk:
                    raise ConnectionError("连接意外断开")
                
                received_data.extend(chunk)
                received_size += len(chunk)
                
                if progress_callback:
                    progress_callback.update(len(chunk))
            
            received_data = bytes(received_data)
            
            # 解密
            if is_encrypted and self.encryption_manager:
                try:
                    received_data = self.encryption_manager.decrypt_data(received_data)
                except Exception as e:
                    print(f"解密文件失败: {e}")
                    return False
            
            # 解压
            if is_compressed:
                try:
                    received_data = self.stream_transfer.decompress_data(received_data)
                except Exception as e:
                    print(f"解压文件失败: {e}")
                    return False
            
            # 写入文件
            with open(full_path, 'wb') as f:
                f.write(received_data)
            
            return True
        except Exception as e:
            print(f"接收文件失败: {e}")
            return False
    
    def delete_file(self, file_path: str) -> bool:
        """删除文件"""
        normalized_path = normalize_path(file_path)
        local_file_path = normalized_path.replace('/', os.sep)
        full_path = self.base_dir / local_file_path
        
        try:
            if full_path.exists():
                if full_path.is_file():
                    full_path.unlink()
                    print(f"文件删除成功: {file_path}")
                elif full_path.is_dir():
                    full_path.rmdir()
                    print(f"目录删除成功: {file_path}")
            
            self.hasher.mark_file_deleted(normalized_path)
            return True
        except Exception as e:
            print(f"删除文件失败 {file_path}: {e}")
            return False
    
    def create_directory(self, dir_path: str) -> bool:
        """创建目录"""
        normalized_path = normalize_path(dir_path)
        local_dir_path = normalized_path.replace('/', os.sep)
        full_path = self.base_dir / local_dir_path
        
        try:
            full_path.mkdir(parents=True, exist_ok=True)
            print(f"目录创建成功: {dir_path}")
            return True
        except Exception as e:
            print(f"创建目录失败 {dir_path}: {e}")
            return False
    
    def send_delete_request(self, sock: socket.socket, file_path: str) -> bool:
        """发送删除请求"""
        try:
            delete_info = {'path': normalize_path(file_path)}
            data = json.dumps(delete_info).encode('utf-8')
            msg = SyncProtocol.pack_message(SyncProtocol.CMD_DELETE_FILE, data)
            sock.sendall(msg)
            
            cmd, _ = SyncProtocol.unpack_message(sock)
            if cmd == SyncProtocol.CMD_OK:
                print(f"远程删除成功: {file_path}")
                return True
            else:
                print(f"远程删除失败: {file_path}")
                return False
        except Exception as e:
            print(f"发送删除请求失败 {file_path}: {e}")
            return False
    
    def update_after_sync(self, server_version: int):
        """同步完成后更新本地状态"""
        self.hasher.update_state_after_sync(server_version)
    
    def compare_states(self, local_state: Dict, remote_state: Dict) -> Dict:
        """比较本地和远程状态（兼容旧API）"""
        sync_plan = {
            'upload': [],
            'download': [],
            'delete_local': [],
            'delete_remote': []
        }
        
        items, _ = SyncPlanner.compute_sync_plan(
            local_state, remote_state,
            0, 0, 'push'
        )
        
        for item in items:
            if item.action == SyncAction.UPLOAD:
                sync_plan['upload'].append(item.path)
            elif item.action == SyncAction.DOWNLOAD:
                sync_plan['download'].append(item.path)
            elif item.action == SyncAction.DELETE_LOCAL:
                sync_plan['delete_local'].append(item.path)
            elif item.action == SyncAction.DELETE_REMOTE:
                sync_plan['delete_remote'].append(item.path)
        
        return sync_plan
