#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步核心逻辑模块
处理文件传输和同步协议，支持加密和进度显示
"""

import json
import socket
import struct
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from sync_tools.utils.file_hasher import FileHasher

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


def normalize_path(path: str) -> str:
    """
    标准化路径分隔符，统一使用正斜杠
    
    Args:
        path: 原始路径
        
    Returns:
        标准化后的路径
    """
    return path.replace(os.sep, '/').replace('\\', '/')


class SyncProtocol:
    """同步协议类"""
    
    # 协议命令
    CMD_HELLO = "HELLO"
    CMD_GET_STATE = "GET_STATE" 
    CMD_SYNC_REQUEST = "SYNC_REQUEST"
    CMD_FILE_DATA = "FILE_DATA"
    CMD_DELETE_FILE = "DELETE_FILE"
    CMD_CREATE_DIR = "CREATE_DIR"
    CMD_SYNC_COMPLETE = "SYNC_COMPLETE"
    CMD_ERROR = "ERROR"
    CMD_OK = "OK"
    
    @staticmethod
    def pack_message(command: str, data: bytes = b"") -> bytes:
        """
        打包消息
        
        Args:
            command: 命令字符串
            data: 数据内容
            
        Returns:
            打包后的消息
        """
        cmd_bytes = command.encode('utf-8')
        cmd_len = len(cmd_bytes)
        data_len = len(data)
        
        # 格式: cmd_len(4) + cmd + data_len(4) + data
        header = struct.pack('!II', cmd_len, data_len)
        return header + cmd_bytes + data
    
    @staticmethod
    def unpack_message(sock: socket.socket) -> Tuple[str, bytes]:
        """
        解包消息
        
        Args:
            sock: socket连接
            
        Returns:
            (命令, 数据)元组
        """
        # 读取头部
        header = SyncProtocol._recv_exact(sock, 8)
        if not header:
            raise ConnectionError("连接已断开")
        
        cmd_len, data_len = struct.unpack('!II', header)
        
        # 读取命令
        cmd_bytes = SyncProtocol._recv_exact(sock, cmd_len)
        if not cmd_bytes:
            raise ConnectionError("读取命令失败")
        
        command = cmd_bytes.decode('utf-8')
        
        # 读取数据
        data = b""
        if data_len > 0:
            data = SyncProtocol._recv_exact(sock, data_len)
            if not data:
                raise ConnectionError("读取数据失败")
        
        return command, data
    
    @staticmethod
    def _recv_exact(sock: socket.socket, length: int) -> bytes:
        """
        精确接收指定长度的数据
        
        Args:
            sock: socket连接
            length: 要接收的字节数
            
        Returns:
            接收到的数据
        """
        data = b""
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                break
            data += chunk
        return data


class SyncCore:
    """同步核心类"""
    
    def __init__(self, base_dir: str, sync_json: Optional[str] = None, 
                 encryption_manager: Optional[Any] = None,
                 progress_manager: Optional[Any] = None):
        """
        初始化同步核心
        
        Args:
            base_dir: 基础目录
            sync_json: 同步状态文件路径
            encryption_manager: 加密管理器
            progress_manager: 进度管理器
        """
        self.base_dir = Path(base_dir).resolve()
        self.hasher = FileHasher(str(self.base_dir), sync_json)
        self.encryption_manager = encryption_manager
        self.progress_manager = progress_manager
    
    def prepare_sync_data(self, file_list: Optional[List[str]] = None) -> Dict:
        """
        准备同步数据
        
        Args:
            file_list: 要同步的文件列表，None表示所有文件
            
        Returns:
            同步数据字典
        """
        current_state = self.hasher.scan_directory()
        
        if file_list:
            # 只同步指定文件
            filtered_state = {f: current_state[f] for f in file_list if f in current_state}
            return filtered_state
        
        return current_state
    
    def send_file(self, sock: socket.socket, file_path: str) -> bool:
        """
        发送文件到socket，支持加密和进度显示
        
        Args:
            sock: socket连接
            file_path: 相对文件路径
            
        Returns:
            发送是否成功
        """
        # 标准化路径，确保跨平台兼容性
        normalized_path = normalize_path(file_path)
        full_path = self.base_dir / file_path
        
        if not full_path.exists() or not full_path.is_file():
            print(f"文件不存在: {full_path}")
            return False
        
        try:
            file_size = full_path.stat().st_size
            
            # 读取文件内容
            with open(full_path, 'rb') as f:
                file_data = f.read()
            
            # 加密整个文件（如果启用加密）
            if self.encryption_manager:
                file_data = self.encryption_manager.encrypt_data(file_data)
            
            # 发送文件信息（使用标准化路径）
            file_info = {
                'path': normalized_path,
                'size': file_size,
                'hash': self.hasher.calculate_file_hash(full_path),
                'encrypted': self.encryption_manager is not None,
                'encrypted_size': len(file_data) if self.encryption_manager else file_size
            }
            
            info_data = json.dumps(file_info).encode('utf-8')
            msg = SyncProtocol.pack_message(SyncProtocol.CMD_FILE_DATA, info_data)
            sock.sendall(msg)
            
            # 等待确认
            cmd, _ = SyncProtocol.unpack_message(sock)
            if cmd != SyncProtocol.CMD_OK:
                print(f"服务端拒绝接收文件: {file_path}")
                return False
            
            # 创建进度回调（使用实际传输大小）
            transfer_size = len(file_data)
            progress_callback = None
            if self.progress_manager and ProgressCallback:
                progress_callback = ProgressCallback(self.progress_manager, "发送")
                progress_callback.start(transfer_size, file_path)
            
            # 分块发送数据
            bytes_sent = 0
            for i in range(0, len(file_data), 8192):
                chunk = file_data[i:i+8192]
                sock.sendall(chunk)
                bytes_sent += len(chunk)
                
                # 更新进度
                if progress_callback:
                    progress_callback.update(len(chunk))
            
            # 完成进度
            if progress_callback:
                progress_callback.finish(True)
            
            print(f"文件发送成功: {file_path} ({bytes_sent:,} 字节)")
            return True
            
        except Exception as e:
            print(f"发送文件失败 {file_path}: {e}")
            if progress_callback:
                progress_callback.finish(False)
            return False
    
    def receive_file(self, sock: socket.socket, file_info: Dict) -> bool:
        """
        从socket接收文件，支持解密和进度显示
        
        Args:
            sock: socket连接
            file_info: 文件信息字典
            
        Returns:
            接收是否成功
        """
        file_path = file_info['path']
        file_size = file_info['size']  # 原始文件大小
        expected_hash = file_info['hash']
        is_encrypted = file_info.get('encrypted', False)
        encrypted_size = file_info.get('encrypted_size', file_size)  # 加密后的大小
        
        # 标准化路径并转换为本地路径分隔符
        normalized_path = normalize_path(file_path)
        # 将标准化路径转换为本地系统路径
        local_file_path = normalized_path.replace('/', os.sep)
        full_path = self.base_dir / local_file_path
        
        try:
            # 确保目录存在
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 发送确认信息
            msg = SyncProtocol.pack_message(SyncProtocol.CMD_OK)
            sock.sendall(msg)
            
            # 创建进度回调（使用实际传输大小）
            transfer_size = encrypted_size if is_encrypted else file_size
            progress_callback = None
            if self.progress_manager and ProgressCallback:
                progress_callback = ProgressCallback(self.progress_manager, "接收")
                progress_callback.start(transfer_size, file_path)
            
            # 接收文件内容
            received_size = 0
            received_data = b""
            
            while received_size < transfer_size:
                remaining = transfer_size - received_size
                chunk_size = min(8192, remaining)
                chunk = sock.recv(chunk_size)
                
                if not chunk:
                    raise ConnectionError("连接意外断开")
                
                received_data += chunk
                received_size += len(chunk)
                
                # 更新进度
                if progress_callback:
                    progress_callback.update(len(chunk))
            
            # 处理接收到的数据
            if is_encrypted and self.encryption_manager:
                # 解密数据
                try:
                    decrypted_data = self.encryption_manager.decrypt_data(received_data)
                    with open(full_path, 'wb') as f:
                        f.write(decrypted_data)
                except Exception as e:
                    print(f"解密文件失败: {e}")
                    if full_path.exists():
                        full_path.unlink()
                    if progress_callback:
                        progress_callback.finish(False)
                    return False
            else:
                # 未加密，直接写入
                with open(full_path, 'wb') as f:
                    f.write(received_data)
            
            # 验证文件hash
            print(f"[DEBUG] 开始验证文件hash: {file_path}")
            actual_hash = self.hasher.calculate_file_hash(full_path)
            print(f"[DEBUG] 期望hash: {expected_hash}")
            print(f"[DEBUG] 实际hash: {actual_hash}")
            
            if actual_hash != expected_hash:
                print(f"文件hash校验失败: {file_path}")
                print(f"  期望: {expected_hash}")
                print(f"  实际: {actual_hash}")
                if full_path.exists():
                    print(f"  文件大小: {full_path.stat().st_size}")
                    full_path.unlink()  # 删除损坏文件
                if progress_callback:
                    progress_callback.finish(False)
                return False
            
            # 完成进度
            if progress_callback:
                progress_callback.finish(True)
            
            print(f"文件接收成功: {file_path} ({received_size:,} 字节)")
            return True
            
        except Exception as e:
            print(f"接收文件失败 {file_path}: {e}")
            if full_path.exists():
                full_path.unlink()
            if progress_callback:
                progress_callback.finish(False)
            return False
    
    def create_directory(self, dir_path: str) -> bool:
        """
        创建目录
        
        Args:
            dir_path: 目录路径
            
        Returns:
            创建是否成功
        """
        # 标准化路径并转换为本地路径分隔符
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
    
    def delete_file(self, file_path: str) -> bool:
        """
        删除文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            删除是否成功
        """
        # 标准化路径并转换为本地路径分隔符
        normalized_path = normalize_path(file_path)
        local_file_path = normalized_path.replace('/', os.sep)
        full_path = self.base_dir / local_file_path
        
        try:
            if full_path.exists():
                if full_path.is_file():
                    full_path.unlink()
                elif full_path.is_dir():
                    full_path.rmdir()  # 只删除空目录
                print(f"文件删除成功: {file_path}")
            return True
        except Exception as e:
            print(f"删除文件失败 {file_path}: {e}")
            return False
    
    def compare_states(self, local_state: Dict, remote_state: Dict) -> Dict:
        """
        比较本地和远程状态
        
        Args:
            local_state: 本地状态
            remote_state: 远程状态
            
        Returns:
            差异信息
        """
        sync_plan = {
            'upload': [],      # 需要上传的文件
            'download': [],    # 需要下载的文件
            'delete_local': [],  # 需要删除的本地文件
            'delete_remote': []  # 需要删除的远程文件
        }
        
        # 检查本地文件
        for file_path, file_info in local_state.items():
            if file_path not in remote_state:
                # 本地有，远程没有 -> 上传
                sync_plan['upload'].append(file_path)
            elif remote_state[file_path]['hash'] != file_info['hash']:
                # hash不同 -> 比较修改时间决定方向
                local_time = file_info.get('modified', '')
                remote_time = remote_state[file_path].get('modified', '')
                
                if local_time > remote_time:
                    sync_plan['upload'].append(file_path)
                else:
                    sync_plan['download'].append(file_path)
        
        # 检查远程文件
        for file_path, file_info in remote_state.items():
            if file_path not in local_state:
                # 远程有，本地没有 -> 下载
                sync_plan['download'].append(file_path)
        
        return sync_plan
