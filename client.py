#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件同步客户端
连接服务端并执行文件同步操作，支持配置文件、加密和进度显示
"""

import socket
import argparse
import json
import sys
from pathlib import Path
from typing import Dict
from sync_tools.core.sync_core import SyncCore, SyncProtocol
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


class SyncClient:
    """同步客户端类"""
    
    def __init__(self, config_manager: ConfigManager):
        """
        初始化客户端
        
        Args:
            config_manager: 配置管理器
        """
        self.config_manager = config_manager
        client_config = config_manager.get_client_config()
        
        self.local_dir = Path(client_config.get("local_dir", "./client_files")).resolve()
        self.sync_json = client_config.get("sync_json", "./client_sync_state.json")
        self.server_address = client_config.get("server_address", "127.0.0.1:8888")
        self.timeout = client_config.get("timeout", 30)
        self.retry_count = client_config.get("retry_count", 3)
        
        # 初始化加密管理器
        self.encryption_manager = None
        if config_manager.is_encryption_enabled("client") and CRYPTO_AVAILABLE and EncryptionManager:
            encryption_config = config_manager.get_encryption_config("client")
            key_file = encryption_config.get("key_file", "./client.key")
            try:
                self.encryption_manager = EncryptionManager(key_file=key_file)
                print(f"[OK] 客户端加密已启用，密钥文件: {key_file}")
            except Exception as e:
                print(f"[ERROR] 加密初始化失败: {e}")
                print("客户端将以未加密模式运行")
        
        # 初始化进度管理器
        self.progress_manager = None
        if create_progress_manager:
            progress_config = config_manager.get_progress_config()
            self.progress_manager = create_progress_manager(progress_config)
        
        # 初始化同步核心
        self.sync_core = SyncCore(
            str(self.local_dir),
            self.sync_json,
            self.encryption_manager,
            self.progress_manager
        )
        
        self.socket = None
        
        # 确保本地目录存在
        self.local_dir.mkdir(parents=True, exist_ok=True)
        print(f"客户端同步目录: {self.local_dir}")
        if self.sync_json:
            print(f"同步状态文件: {self.sync_json}")
    
    def connect(self, server_host: str, server_port: int) -> bool:
        """
        连接到服务端
        
        Args:
            server_host: 服务端地址
            server_port: 服务端端口
            
        Returns:
            连接是否成功
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((server_host, server_port))
            
            # 发送Hello握手
            client_info = {
                "name": "SyncClient",
                "version": "1.0",
                "local_dir": str(self.local_dir)
            }
            
            hello_data = json.dumps(client_info).encode('utf-8')
            hello_msg = SyncProtocol.pack_message(SyncProtocol.CMD_HELLO, hello_data)
            self.socket.sendall(hello_msg)
            
            # 接收服务端响应
            cmd, data = SyncProtocol.unpack_message(self.socket)
            if cmd == SyncProtocol.CMD_OK:
                server_info = json.loads(data.decode('utf-8'))
                print(f"连接服务端成功: {server_info}")
                return True
            else:
                print(f"服务端握手失败: {cmd}")
                return False
                
        except Exception as e:
            print(f"连接服务端失败: {e}")
            return False
    
    def disconnect(self):
        """断开连接"""
        if self.socket:
            self.socket.close()
            self.socket = None
    
    def get_server_state(self) -> Dict:
        """
        获取服务端文件状态
        
        Returns:
            服务端文件状态字典
        """
        try:
            if not self.socket:
                raise Exception("未连接到服务端")
                
            # 发送获取状态请求
            msg = SyncProtocol.pack_message(SyncProtocol.CMD_GET_STATE)
            self.socket.sendall(msg)
            
            # 接收响应
            cmd, data = SyncProtocol.unpack_message(self.socket)
            if cmd == SyncProtocol.CMD_OK:
                server_state = json.loads(data.decode('utf-8'))
                print(f"获取服务端状态成功，包含 {len(server_state)} 个文件")
                return server_state
            else:
                print(f"获取服务端状态失败: {cmd}")
                return {}
                
        except Exception as e:
            print(f"获取服务端状态失败: {e}")
            return {}
    
    def push_to_server(self) -> bool:
        """
        推送本地文件到服务端
        
        Returns:
            推送是否成功
        """
        try:
            # 获取本地状态
            local_state = self.sync_core.prepare_sync_data()
            print(f"本地文件数量: {len(local_state)}")
            
            if not self.socket:
                raise Exception("未连接到服务端")
            
            # 发送同步请求
            sync_request = {
                'mode': 'push',
                'client_state': local_state
            }
            
            request_data = json.dumps(sync_request).encode('utf-8')
            msg = SyncProtocol.pack_message(SyncProtocol.CMD_SYNC_REQUEST, request_data)
            self.socket.sendall(msg)
            
            # 接收同步计划
            cmd, data = SyncProtocol.unpack_message(self.socket)
            if cmd != SyncProtocol.CMD_OK:
                print(f"服务端拒绝同步请求: {cmd}")
                return False
            
            sync_plan = json.loads(data.decode('utf-8'))
            server_state = sync_plan['server_state']
            # 在推送模式下，映射关系是对应的
            files_to_send = sync_plan['files_to_receive']     # 客户端需要发送的文件
            files_to_receive = sync_plan['files_to_send']     # 客户端需要接收的文件
            
            print(f"同步计划: 发送 {len(files_to_send)} 个文件，接收 {len(files_to_receive)} 个文件")
            
            # 发送文件
            success_count = 0
            for file_path in files_to_send:
                if self.sync_core.send_file(self.socket, file_path):
                    success_count += 1
            
            print(f"推送完成: {success_count}/{len(files_to_send)} 个文件成功")
            
            # 接收服务端发送的文件
            if files_to_receive:
                print("接收服务端文件...")
                for file_path in files_to_receive:
                    # 这里需要实现接收逻辑，当前简化处理
                    pass
            
            # 更新本地状态
            self.sync_core.hasher.update_state()
            return True
            
        except Exception as e:
            print(f"推送失败: {e}")
            return False
    
    def pull_from_server(self) -> bool:
        """
        从服务端拉取文件
        
        Returns:
            拉取是否成功
        """
        try:
            print("开始从服务端拉取文件...")
            
            # 获取本地状态
            local_state = self.sync_core.prepare_sync_data()
            print(f"本地文件数量: {len(local_state)}")
            
            if not self.socket:
                raise Exception("未连接到服务端")
            
            # 发送同步请求
            sync_request = {
                'mode': 'pull',
                'client_state': local_state
            }
            
            request_data = json.dumps(sync_request).encode('utf-8')
            msg = SyncProtocol.pack_message(SyncProtocol.CMD_SYNC_REQUEST, request_data)
            self.socket.sendall(msg)
            
            # 接收同步计划
            cmd, data = SyncProtocol.unpack_message(self.socket)
            if cmd != SyncProtocol.CMD_OK:
                print(f"服务端拒绝同步请求: {cmd}")
                return False
            
            sync_plan = json.loads(data.decode('utf-8'))
            server_state = sync_plan['server_state']
            # 在拉取模式下，服务端的files_to_send就是客户端需要接收的文件
            files_to_receive = sync_plan['files_to_send']     # 客户端需要接收的文件  
            files_to_send = sync_plan['files_to_receive']     # 客户端需要发送的文件
            
            print(f"同步计划: 接收 {len(files_to_receive)} 个文件，发送 {len(files_to_send)} 个文件")
            
            # 在拉取模式下，服务端会主动发送文件，客户端只需要接收
            if files_to_receive:
                print("等待服务端发送文件...")
                received_count = 0
                
                for _ in range(len(files_to_receive)):
                    try:
                        cmd, data = SyncProtocol.unpack_message(self.socket)
                        if cmd == SyncProtocol.CMD_FILE_DATA:
                            file_info = json.loads(data.decode('utf-8'))
                            if self.sync_core.receive_file(self.socket, file_info):
                                received_count += 1
                        else:
                            print(f"收到意外命令: {cmd}")
                            break
                    except Exception as e:
                        print(f"接收文件失败: {e}")
                        break
                
                print(f"拉取完成: {received_count}/{len(files_to_receive)} 个文件成功")
            else:
                print("没有需要接收的文件")
            
            # 发送客户端文件到服务端（如果有需要）
            if files_to_send:
                print("发送本地文件到服务端...")
                for file_path in files_to_send:
                    if self.sync_core.send_file(self.socket, file_path):
                        print(f"发送成功: {file_path}")
                    else:
                        print(f"发送失败: {file_path}")
            
            # 更新本地状态
            self.sync_core.hasher.update_state()
            return True
            
        except Exception as e:
            print(f"拉取失败: {e}")
            return False
    
    def sync_with_server(self, mode: str, server_host: str, server_port: int) -> bool:
        """
        与服务端同步
        
        Args:
            mode: 同步模式 ('push' 或 'pull')
            server_host: 服务端地址
            server_port: 服务端端口
            
        Returns:
            同步是否成功
        """
        if not self.connect(server_host, server_port):
            return False
        
        try:
            if mode == 'push':
                return self.push_to_server()
            elif mode == 'pull':
                return self.pull_from_server()
            else:
                print(f"不支持的同步模式: {mode}")
                return False
        finally:
            self.disconnect()
    
    def list_local_files(self):
        """列出本地文件"""
        print(f"\n本地文件目录: {self.local_dir}")
        files = self.sync_core.hasher.get_file_list()
        if files:
            print("文件列表:")
            for file_path in sorted(files):
                print(f"  {file_path}")
        else:
            print("目录为空")
    
    def show_changes(self):
        """显示文件变化"""
        print("\n文件变化检测:")
        changes = self.sync_core.hasher.get_changes()
        
        for change_type, files in changes.items():
            if files:
                print(f"\n{change_type.upper()}:")
                for file_path in files:
                    print(f"  {file_path}")


def parse_server_address(server_str: str) -> tuple:
    """
    解析服务端地址
    
    Args:
        server_str: 服务端地址字符串 (格式: host:port)
        
    Returns:
        (host, port) 元组
    """
    try:
        if ':' in server_str:
            host, port = server_str.split(':', 1)
            return host, int(port)
        else:
            return server_str, 8888
    except ValueError:
        raise ValueError(f"无效的服务端地址格式: {server_str}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='文件同步客户端')
    parser.add_argument('--config', '-c', help='配置文件路径')
    parser.add_argument('--mode', choices=['push', 'pull', 'list', 'changes'], 
                       default='list', help='操作模式')
    parser.add_argument('--local-dir', help='本地同步目录（覆盖配置文件）')
    parser.add_argument('--sync-json', help='同步状态文件（覆盖配置文件）')
    parser.add_argument('--server', help='服务端地址（覆盖配置文件）')
    
    args = parser.parse_args()
    
    # 加载配置
    config_manager = ConfigManager(args.config)
    
    # 命令行参数覆盖配置文件
    if args.local_dir:
        config_manager.config['client']['local_dir'] = args.local_dir
    if args.sync_json:
        config_manager.config['client']['sync_json'] = args.sync_json
    if args.server:
        config_manager.config['client']['server_address'] = args.server
    
    # 验证配置
    if not config_manager.validate_config(for_server=False):
        print("配置验证失败，退出")
        return
    
    client = SyncClient(config_manager)
    
    if args.mode == 'list':
        client.list_local_files()
    elif args.mode == 'changes':
        client.show_changes()
    elif args.mode in ['push', 'pull']:
        try:
            # 从配置获取服务端地址
            server_address = client.server_address
            host, port = parse_server_address(server_address)
            
            # 启动总体进度跟踪
            if client.progress_manager:
                # 先获取要同步的文件数量
                local_state = client.sync_core.prepare_sync_data()
                client.progress_manager.start_overall_progress(
                    len(local_state), 
                    f"{args.mode.upper()} 同步"
                )
            
            success = client.sync_with_server(args.mode, host, port)
            
            # 结束总体进度跟踪
            if client.progress_manager:
                client.progress_manager.finish_overall_progress()
            
            if success:
                print(f"{args.mode} 操作完成")
                sys.exit(0)
            else:
                print(f"{args.mode} 操作失败")
                sys.exit(1)
        except ValueError as e:
            print(f"错误: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"同步过程中发生错误: {e}")
            if client.progress_manager:
                client.progress_manager.finish_overall_progress()
            sys.exit(1)
    else:
        print(f"不支持的操作模式: {args.mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
