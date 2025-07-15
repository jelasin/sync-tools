#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件同步服务端
监听客户端连接并处理同步请求，支持配置文件、加密和进度显示
"""

import socket
import threading
import argparse
import json
import os
from pathlib import Path
from typing import Dict, Optional
from sync_tools.core.sync_core import SyncCore, SyncProtocol
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
        
        Args:
            config_manager: 配置管理器
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
        
        self.running = False
        self.server_socket = None
        
        # 确保同步目录存在
        self.sync_dir.mkdir(parents=True, exist_ok=True)
        print(f"服务端同步目录: {self.sync_dir}")
        if self.sync_json:
            print(f"同步状态文件: {self.sync_json}")
    
    def start(self):
        """启动服务端"""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.running = True
            
            print(f"同步服务端启动成功，监听 {self.host}:{self.port}")
            print(f"同步目录: {self.sync_dir}")
            print("等待客户端连接...")
            
            while self.running:
                try:
                    client_socket, client_address = self.server_socket.accept()
                    print(f"客户端连接: {client_address}")
                    
                    # 为每个客户端创建处理线程
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, client_address)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                except socket.error as e:
                    if self.running:
                        print(f"接受连接失败: {e}")
                    break
                    
        except Exception as e:
            print(f"服务端启动失败: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """停止服务端"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        print("服务端已停止")
    
    def handle_client(self, client_socket: socket.socket, client_address):
        """
        处理客户端连接
        
        Args:
            client_socket: 客户端socket
            client_address: 客户端地址
        """
        try:
            while True:
                # 接收客户端命令
                command, data = SyncProtocol.unpack_message(client_socket)
                
                if command == SyncProtocol.CMD_HELLO:
                    self.handle_hello(client_socket, data)
                    
                elif command == SyncProtocol.CMD_GET_STATE:
                    self.handle_get_state(client_socket)
                    
                elif command == SyncProtocol.CMD_SYNC_REQUEST:
                    self.handle_sync_request(client_socket, data)
                    
                elif command == SyncProtocol.CMD_FILE_DATA:
                    self.handle_file_data(client_socket, data)
                    
                elif command == SyncProtocol.CMD_DELETE_FILE:
                    self.handle_delete_file(client_socket, data)
                    
                elif command == SyncProtocol.CMD_CREATE_DIR:
                    self.handle_create_dir(client_socket, data)
                    
                else:
                    print(f"未知命令: {command}")
                    error_msg = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Unknown command")
                    client_socket.sendall(error_msg)
                    
        except ConnectionError:
            print(f"客户端断开连接: {client_address}")
        except Exception as e:
            print(f"处理客户端请求失败: {e}")
        finally:
            client_socket.close()
    
    def handle_hello(self, client_socket: socket.socket, data: bytes):
        """处理Hello握手"""
        try:
            client_info = json.loads(data.decode('utf-8'))
            print(f"客户端信息: {client_info}")
            
            server_info = {
                "name": "SyncServer",
                "version": "1.0",
                "sync_dir": str(self.sync_dir)
            }
            
            response_data = json.dumps(server_info).encode('utf-8')
            response = SyncProtocol.pack_message(SyncProtocol.CMD_OK, response_data)
            client_socket.sendall(response)
            
        except Exception as e:
            print(f"处理Hello失败: {e}")
            error_msg = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Hello failed")
            client_socket.sendall(error_msg)
    
    def handle_get_state(self, client_socket: socket.socket):
        """处理获取状态请求"""
        try:
            # 获取服务端文件状态
            server_state = self.sync_core.prepare_sync_data()
            
            state_data = json.dumps(server_state).encode('utf-8')
            response = SyncProtocol.pack_message(SyncProtocol.CMD_OK, state_data)
            client_socket.sendall(response)
            
            print(f"发送服务端状态，包含 {len(server_state)} 个文件")
            
        except Exception as e:
            print(f"获取状态失败: {e}")
            error_msg = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Get state failed")
            client_socket.sendall(error_msg)
    
    def handle_sync_request(self, client_socket: socket.socket, data: bytes):
        """处理同步请求"""
        try:
            sync_request = json.loads(data.decode('utf-8'))
            client_state = sync_request.get('client_state', {})
            sync_mode = sync_request.get('mode', 'push')  # push 或 pull
            
            print(f"收到同步请求，模式: {sync_mode}")
            
            # 获取服务端状态
            server_state = self.sync_core.prepare_sync_data()
            
            # 比较状态并生成同步计划
            if sync_mode == 'push':
                # 客户端推送模式：客户端的文件推送到服务端
                sync_plan = self.sync_core.compare_states(server_state, client_state)
                files_to_receive = sync_plan['download']  # 服务端需要下载的文件
                files_to_send = sync_plan['upload']       # 服务端需要发送的文件
            else:
                # 客户端拉取模式：服务端的文件发送给客户端
                sync_plan = self.sync_core.compare_states(client_state, server_state)
                files_to_receive = sync_plan['upload']    # 服务端需要接收的文件
                files_to_send = sync_plan['download']     # 服务端需要发送的文件
            
            # 发送同步计划
            response_data = {
                'server_state': server_state,
                'files_to_send': files_to_send,
                'files_to_receive': files_to_receive
            }
            
            response_json = json.dumps(response_data).encode('utf-8')
            response = SyncProtocol.pack_message(SyncProtocol.CMD_OK, response_json)
            client_socket.sendall(response)
            
            print(f"同步计划: 发送 {len(files_to_send)} 个文件，接收 {len(files_to_receive)} 个文件")
            
            # 如果是拉取模式，服务端需要主动发送文件
            if sync_mode == 'pull' and files_to_send:
                print("开始发送文件到客户端...")
                for file_path in files_to_send:
                    success = self.sync_core.send_file(client_socket, file_path)
                    if success:
                        print(f"文件发送成功: {file_path}")
                    else:
                        print(f"文件发送失败: {file_path}")
                
                # 更新状态
                self.sync_core.hasher.update_state()
            
        except Exception as e:
            print(f"处理同步请求失败: {e}")
            error_msg = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Sync request failed")
            client_socket.sendall(error_msg)
    
    def handle_file_data(self, client_socket: socket.socket, data: bytes):
        """处理文件数据"""
        try:
            file_info = json.loads(data.decode('utf-8'))
            print(f"接收文件: {file_info['path']}")
            
            # 接收文件
            success = self.sync_core.receive_file(client_socket, file_info)
            
            if success:
                # 更新本地状态
                self.sync_core.hasher.update_state()
                print(f"文件保存成功: {file_info['path']}")
            else:
                print(f"文件保存失败: {file_info['path']}")
                
        except Exception as e:
            print(f"处理文件数据失败: {e}")
    
    def handle_delete_file(self, client_socket: socket.socket, data: bytes):
        """处理删除文件请求"""
        try:
            delete_info = json.loads(data.decode('utf-8'))
            file_path = delete_info['path']
            
            success = self.sync_core.delete_file(file_path)
            
            if success:
                response = SyncProtocol.pack_message(SyncProtocol.CMD_OK)
                self.sync_core.hasher.update_state()
            else:
                response = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Delete failed")
            
            client_socket.sendall(response)
            
        except Exception as e:
            print(f"删除文件失败: {e}")
            error_msg = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Delete failed")
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
            print(f"创建目录失败: {e}")
            error_msg = SyncProtocol.pack_message(SyncProtocol.CMD_ERROR, b"Create dir failed")
            client_socket.sendall(error_msg)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='文件同步服务端')
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
