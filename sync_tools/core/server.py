#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件同步服务端
支持版本控制、冲突检测和多客户端并发

核心设计：
1. 全局版本号：每次有变更时递增
2. 冲突检测：比较客户端base_version与当前版本
3. 线程安全：使用锁保护共享状态
"""

import socket
import threading
import argparse
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
from sync_tools.core.sync_core import SyncCore, SyncProtocol, SyncPlanner, SyncAction
from sync_tools.utils.file_hasher import FileHasher
from sync_tools.utils.config_manager import ConfigManager

try:
    from sync_tools.utils.encryption import EncryptionManager, CRYPTO_AVAILABLE
except ImportError:
    CRYPTO_AVAILABLE = False
    EncryptionManager = None

try:
    from sync_tools.utils.progress import FileTransferProgress, create_progress_manager
except ImportError:
    FileTransferProgress = None
    create_progress_manager = None


class SyncServer:
    """同步服务端类"""
    
    def __init__(self, config_manager: ConfigManager):
        """
        初始化服务端
        """
        self.config_manager = config_manager
        server_config = config_manager.get_server_config()
        
        self.host = server_config.get("host", "0.0.0.0")
        self.port = server_config.get("port", 8888)
        self.sync_dir = Path(server_config.get("sync_dir", "./server_files")).resolve()
        self.sync_json = server_config.get("sync_json", "./server_sync_state.json")
        self.max_connections = server_config.get("max_connections", 10)
        
        # 初始化加密管理器
        self.encryption_manager = None
        if config_manager.is_encryption_enabled("server") and CRYPTO_AVAILABLE and EncryptionManager:
            encryption_config = config_manager.get_encryption_config("server")
            key_file = encryption_config.get("key_file", "./server.key")
            try:
                self.encryption_manager = EncryptionManager(key_file=key_file)
                print(f"[OK] 服务端加密已启用，密钥文件: {key_file}")
            except Exception as e:
                print(f"[ERROR] 加密初始化失败: {e}")
                print("服务端将以未加密模式运行")
        
        # 初始化进度管理器
        self.progress_manager = None
        if create_progress_manager:
            progress_config = config_manager.get_progress_config()
            self.progress_manager = create_progress_manager(progress_config)
        
        # 初始化同步核心
        self.sync_core = SyncCore(
            str(self.sync_dir), 
            self.sync_json,
            self.encryption_manager,
            self.progress_manager
        )
        
        # 全局版本号 - 每次有变更时递增
        self._version_lock = threading.Lock()
        self._current_version = self._load_version()
        
        # 连接的客户端信息
        self._clients_lock = threading.Lock()
        self._connected_clients: Dict[str, dict] = {}
        
        self.running = False
        self.server_socket = None
        
        # 确保同步目录存在
        self.sync_dir.mkdir(parents=True, exist_ok=True)
        print(f"服务端同步目录: {self.sync_dir}")
        print(f"当前版本号: {self._current_version}")
        if self.sync_json:
            print(f"同步状态文件: {self.sync_json}")
    
    def _load_version(self) -> int:
        """从状态文件加载版本号"""
        return self.sync_core.hasher.sync_state.sync_version
    
    def _increment_version(self) -> int:
        """递增版本号"""
        with self._version_lock:
            self._current_version += 1
            # 保存到状态文件
            self.sync_core.hasher.sync_state.sync_version = self._current_version
            self.sync_core.hasher.save_state()
            return self._current_version
    
    def get_current_version(self) -> int:
        """获取当前版本号"""
        with self._version_lock:
            return self._current_version
    
    def start(self):
        """启动服务端"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(self.max_connections)
            self.running = True
            
            print(f"\n{'='*50}")
            print(f"同步服务端 v2.0 启动成功")
            print(f"{'='*50}")
            print(f"监听地址: {self.host}:{self.port}")
            print(f"同步目录: {self.sync_dir}")
            print(f"当前版本: {self._current_version}")
            print(f"等待客户端连接...")
            print(f"{'='*50}\n")
            
            while self.running:
                try:
                    client_socket, client_address = self.server_socket.accept()
                    print(f"\n[连接] 新客户端: {client_address}")
                    
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, client_address)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                except socket.error as e:
                    if self.running:
                        print(f"[错误] 接受连接失败: {e}")
                    break
                    
        except Exception as e:
            print(f"[错误] 服务端启动失败: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """停止服务端"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        print("\n服务端已停止")
    
    def handle_client(self, client_socket: socket.socket, client_address):
        """处理客户端连接"""
        client_id = None
        try:
            while True:
                command, data = SyncProtocol.unpack_message(client_socket)
                
                if command == SyncProtocol.CMD_HELLO:
                    client_id = self.handle_hello(client_socket, data, client_address)
                    
                elif command == SyncProtocol.CMD_GET_STATE:
                    self.handle_get_state(client_socket)
                    
                elif command == SyncProtocol.CMD_SYNC_REQUEST:
                    self.handle_sync_request(client_socket, data)
                    
                elif command == SyncProtocol.CMD_FILE_DATA:
                    self.handle_file_data(client_socket, data)
                    
                elif command == SyncProtocol.CMD_DELETE_FILE:
                    self.handle_delete_file(client_socket, data)
                    
                elif command == SyncProtocol.CMD_SYNC_COMPLETE:
                    self.handle_sync_complete(client_socket, data)
                    
                elif command == SyncProtocol.CMD_CREATE_DIR:
                    self.handle_create_dir(client_socket, data)
                    
                else:
                    print(f"[警告] 未知命令: {command}")
                    error_msg = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Unknown command")
                    client_socket.sendall(error_msg)
                    
        except ConnectionError:
            print(f"[断开] 客户端断开连接: {client_address}")
        except Exception as e:
            print(f"[错误] 处理客户端请求失败: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if client_id:
                with self._clients_lock:
                    self._connected_clients.pop(client_id, None)
            client_socket.close()
    
    def handle_hello(self, client_socket: socket.socket, data: bytes, client_address) -> str:
        """处理Hello握手"""
        try:
            client_info = json.loads(data.decode('utf-8'))
            client_id = client_info.get('client_id', str(client_address))
            print(f"[握手] 客户端: {client_id}")
            print(f"        版本: {client_info.get('version', '?')}")
            
            # 记录客户端
            with self._clients_lock:
                self._connected_clients[client_id] = {
                    'address': client_address,
                    'connected_at': datetime.now().isoformat(),
                    'info': client_info
                }
            
            server_info = {
                "name": "SyncServer",
                "version": "2.0",
                "sync_dir": str(self.sync_dir),
                "server_version": self.get_current_version()
            }
            
            response_data = json.dumps(server_info).encode('utf-8')
            response = SyncProtocol.pack_message(SyncProtocol.CMD_OK, response_data)
            client_socket.sendall(response)
            
            return client_id
            
        except Exception as e:
            print(f"[错误] 处理Hello失败: {e}")
            error_msg = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Hello failed")
            client_socket.sendall(error_msg)
            return None
    
    def handle_get_state(self, client_socket: socket.socket):
        """处理获取状态请求"""
        try:
            server_state = self.sync_core.prepare_sync_data()
            current_version = self.get_current_version()
            
            response_data = {
                'files': server_state,
                'version': current_version
            }
            
            state_data = json.dumps(response_data).encode('utf-8')
            response = SyncProtocol.pack_message(SyncProtocol.CMD_OK, state_data)
            client_socket.sendall(response)
            
            print(f"[状态] 发送服务端状态，版本: {current_version}，文件数: {len(server_state)}")
            
        except Exception as e:
            print(f"[错误] 获取状态失败: {e}")
            error_msg = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Get state failed")
            client_socket.sendall(error_msg)
    
    def handle_sync_request(self, client_socket: socket.socket, data: bytes):
        """处理同步请求"""
        try:
            sync_request = json.loads(data.decode('utf-8'))
            client_state = sync_request.get('client_state', {})
            sync_mode = sync_request.get('mode', 'push')
            client_base_version = sync_request.get('base_version', 0)
            client_id = sync_request.get('client_id', 'unknown')
            
            print(f"\n[同步请求] 客户端: {client_id}")
            print(f"           模式: {sync_mode}")
            print(f"           客户端基准版本: {client_base_version}")
            print(f"           客户端文件数: {len(client_state)}")
            
            # 获取服务端状态
            server_state = self.sync_core.prepare_sync_data()
            current_version = self.get_current_version()
            
            print(f"           服务端当前版本: {current_version}")
            print(f"           服务端文件数: {len(server_state)}")
            
            if sync_mode == 'push':
                self._handle_push_request(
                    client_socket, client_state, server_state,
                    client_base_version, current_version
                )
            else:
                self._handle_pull_request(
                    client_socket, client_state, server_state,
                    current_version
                )
            
        except Exception as e:
            print(f"[错误] 处理同步请求失败: {e}")
            import traceback
            traceback.print_exc()
            error_msg = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Sync request failed")
            client_socket.sendall(error_msg)
    
    def _handle_push_request(
        self, 
        client_socket: socket.socket,
        client_state: Dict,
        server_state: Dict,
        client_base_version: int,
        current_version: int
    ):
        """处理Push请求"""
        # 先更新服务端状态，确保状态是最新的
        self.sync_core.hasher.update_state()
        
        # 重新获取服务端状态
        server_state = self.sync_core.prepare_sync_data()
        
        # 检测版本冲突
        if client_base_version < current_version and client_base_version > 0:
            # 有人在客户端上次同步后推送了更改
            # 检查是否有实际冲突（同一文件被修改）
            conflicts = self._detect_conflicts(client_state, server_state, client_base_version)
            
            if conflicts:
                print(f"[冲突] 检测到 {len(conflicts)} 个冲突文件")
                conflict_info = {
                    'server_version': current_version,
                    'conflicts': conflicts,
                    'message': '服务端版本已更新，存在冲突文件'
                }
                conflict_data = json.dumps(conflict_info).encode('utf-8')
                response = SyncProtocol.pack_message(SyncProtocol.CMD_CONFLICT, conflict_data)
                client_socket.sendall(response)
                return
        
        # 计算同步计划
        sync_items, _ = SyncPlanner.compute_sync_plan(
            client_state, server_state,
            client_base_version, current_version,
            'push'
        )
        
        files_to_upload = []
        files_to_delete = []
        
        for item in sync_items:
            if item.action == SyncAction.UPLOAD:
                files_to_upload.append(item.path)
            elif item.action == SyncAction.DELETE_REMOTE:
                files_to_delete.append(item.path)
        
        print(f"[同步计划] 上传: {len(files_to_upload)}，删除: {len(files_to_delete)}")
        
        # 发送同步计划
        response_data = {
            'server_version': current_version,
            'files_to_upload': files_to_upload,
            'files_to_delete': files_to_delete
        }
        
        response_json = json.dumps(response_data).encode('utf-8')
        response = SyncProtocol.pack_message(SyncProtocol.CMD_OK, response_json)
        client_socket.sendall(response)
    
    def _handle_pull_request(
        self, 
        client_socket: socket.socket,
        client_state: Dict,
        server_state: Dict,
        current_version: int
    ):
        """处理Pull请求"""
        # 先更新服务端状态，确保 tombstone 被正确记录
        self.sync_core.hasher.update_state()
        
        # 重新获取服务端状态（包含最新的 tombstone）
        server_state = self.sync_core.prepare_sync_data()
        
        # 计算同步计划
        sync_items, _ = SyncPlanner.compute_sync_plan(
            client_state, server_state,
            0, current_version,  # Pull模式不检查版本冲突
            'pull'
        )
        
        files_to_download = []
        files_to_delete = []
        
        for item in sync_items:
            if item.action == SyncAction.DOWNLOAD:
                files_to_download.append(item.path)
            elif item.action == SyncAction.DELETE_LOCAL:
                files_to_delete.append(item.path)
        
        print(f"[同步计划] 下载: {len(files_to_download)}，删除: {len(files_to_delete)}")
        
        # 发送同步计划
        response_data = {
            'server_version': current_version,
            'files_to_download': files_to_download,
            'files_to_delete': files_to_delete
        }
        
        response_json = json.dumps(response_data).encode('utf-8')
        response = SyncProtocol.pack_message(SyncProtocol.CMD_OK, response_json)
        client_socket.sendall(response)
        
        # 发送文件
        for file_path in files_to_download:
            print(f"[发送] {file_path}")
            success = self.sync_core.send_file(client_socket, file_path)
            if not success:
                print(f"[错误] 发送文件失败: {file_path}")
    
    def _detect_conflicts(
        self, 
        client_state: Dict, 
        server_state: Dict,
        client_base_version: int
    ) -> List[str]:
        """
        检测冲突文件
        
        冲突条件：
        1. 客户端和服务端都修改了同一个文件
        2. 客户端删除了服务端修改的文件
        3. 服务端删除了客户端修改的文件
        """
        conflicts = []
        
        for path in set(client_state.keys()) | set(server_state.keys()):
            client_info = client_state.get(path)
            server_info = server_state.get(path)
            
            if not client_info or not server_info:
                continue
            
            client_status = client_info.get('status', 'active')
            server_status = server_info.get('status', 'active')
            client_hash = client_info.get('hash', '')
            server_hash = server_info.get('hash', '')
            
            # 两边都是活跃文件且hash不同
            if client_status == 'active' and server_status == 'active':
                if client_hash != server_hash:
                    conflicts.append(path)
            # 一边删除，另一边修改
            elif client_status == 'deleted' and server_status == 'active':
                conflicts.append(path)
            elif client_status == 'active' and server_status == 'deleted':
                conflicts.append(path)
        
        return conflicts
    
    def handle_file_data(self, client_socket: socket.socket, data: bytes):
        """处理文件数据"""
        try:
            file_info = json.loads(data.decode('utf-8'))
            file_path = file_info['path']
            print(f"[接收] {file_path}")
            
            success = self.sync_core.receive_file(client_socket, file_info)
            
            if success:
                print(f"[成功] 文件保存: {file_path}")
            else:
                print(f"[失败] 文件保存: {file_path}")
                
        except Exception as e:
            print(f"[错误] 处理文件数据失败: {e}")
    
    def handle_delete_file(self, client_socket: socket.socket, data: bytes):
        """处理删除文件请求"""
        try:
            delete_info = json.loads(data.decode('utf-8'))
            file_path = delete_info['path']
            
            print(f"[删除] {file_path}")
            success = self.sync_core.delete_file(file_path)
            
            if success:
                response = SyncProtocol.pack_message(SyncProtocol.CMD_OK)
            else:
                response = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Delete failed")
            
            client_socket.sendall(response)
            
        except Exception as e:
            print(f"[错误] 删除文件失败: {e}")
            error_msg = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Delete failed")
            client_socket.sendall(error_msg)
    
    def handle_sync_complete(self, client_socket: socket.socket, data: bytes):
        """处理同步完成信号"""
        try:
            complete_info = json.loads(data.decode('utf-8'))
            uploaded = complete_info.get('uploaded', 0)
            deleted = complete_info.get('deleted', 0)
            
            print(f"[完成] 上传: {uploaded}，删除: {deleted}")
            
            # 如果有变更，递增版本号
            if uploaded > 0 or deleted > 0:
                new_version = self._increment_version()
                # 更新服务端状态
                self.sync_core.hasher.update_state()
            else:
                new_version = self.get_current_version()
            
            response_data = {
                'new_version': new_version,
                'message': 'Sync completed'
            }
            
            response_json = json.dumps(response_data).encode('utf-8')
            response = SyncProtocol.pack_message(SyncProtocol.CMD_OK, response_json)
            client_socket.sendall(response)
            
            print(f"[版本] 当前版本: {new_version}")
            
        except Exception as e:
            print(f"[错误] 处理同步完成失败: {e}")
            error_msg = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Sync complete failed")
            client_socket.sendall(error_msg)
    
    def handle_create_dir(self, client_socket: socket.socket, data: bytes):
        """处理创建目录请求"""
        try:
            dir_info = json.loads(data.decode('utf-8'))
            dir_path = dir_info['path']
            
            success = self.sync_core.create_directory(dir_path)
            
            if success:
                response = SyncProtocol.pack_message(SyncProtocol.CMD_OK)
            else:
                response = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Create dir failed")
            
            client_socket.sendall(response)
            
        except Exception as e:
            print(f"[错误] 创建目录失败: {e}")
            error_msg = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Create dir failed")
            client_socket.sendall(error_msg)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='文件同步服务端 v2.0')
    parser.add_argument('--config', '-c', help='配置文件路径')
    parser.add_argument('--host', help='监听地址（覆盖配置文件）')
    parser.add_argument('--port', type=int, help='监听端口（覆盖配置文件）')
    parser.add_argument('--sync-dir', help='同步目录（覆盖配置文件）')
    parser.add_argument('--sync-json', help='同步状态文件（覆盖配置文件）')
    
    args = parser.parse_args()
    
    # 加载配置
    config_manager = ConfigManager(args.config)
    
    # 命令行参数覆盖配置文件
    if args.host:
        config_manager.config['server']['host'] = args.host
    if args.port:
        config_manager.config['server']['port'] = args.port
    if args.sync_dir:
        config_manager.config['server']['sync_dir'] = args.sync_dir
    if args.sync_json:
        config_manager.config['server']['sync_json'] = args.sync_json
    
    # 验证配置
    if not config_manager.validate_config(for_server=True):
        print("配置验证失败，退出")
        return
    
    server = SyncServer(config_manager)
    
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n收到中断信号，正在停止服务端...")
        server.stop()


if __name__ == "__main__":
    main()
