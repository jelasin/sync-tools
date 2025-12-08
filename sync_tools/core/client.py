#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件同步客户端
支持正确的删除同步、版本控制和冲突检测
"""

import socket
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional
from sync_tools.core.sync_core import SyncCore, SyncProtocol, SyncAction, SyncItem, SyncPlanner
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
        
        # 冲突处理策略: 'ask', 'local', 'remote', 'skip'
        self.conflict_strategy = client_config.get("conflict_strategy", "ask")
        
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
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((server_host, server_port))
            
            # 发送Hello握手
            client_info = {
                "name": "SyncClient",
                "version": "2.0",
                "local_dir": str(self.local_dir),
                "client_id": self.sync_core.hasher.client_id
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
    
    def get_server_state(self) -> tuple:
        """
        获取服务端文件状态和版本号
        
        Returns:
            (服务端文件状态字典, 服务端版本号)
        """
        try:
            if not self.socket:
                raise Exception("未连接到服务端")
            
            msg = SyncProtocol.pack_message(SyncProtocol.CMD_GET_STATE)
            self.socket.sendall(msg)
            
            cmd, data = SyncProtocol.unpack_message(self.socket)
            if cmd == SyncProtocol.CMD_OK:
                response = json.loads(data.decode('utf-8'))
                server_state = response.get('files', {})
                server_version = response.get('version', 0)
                print(f"获取服务端状态成功，版本: {server_version}，文件数: {len(server_state)}")
                return server_state, server_version
            else:
                print(f"获取服务端状态失败: {cmd}")
                return {}, 0
                
        except Exception as e:
            print(f"获取服务端状态失败: {e}")
            return {}, 0
    
    def push_to_server(self) -> bool:
        """
        推送本地变更到服务端
        
        实现逻辑：
        1. 获取本地当前状态和上次同步的基准版本
        2. 获取服务端当前状态和版本号
        3. 计算需要上传、删除的文件
        4. 检测冲突
        5. 执行同步操作
        """
        try:
            print("\n" + "="*50)
            print("开始推送到服务端...")
            print("="*50)
            
            if not self.socket:
                raise Exception("未连接到服务端")
            
            # 获取本地状态
            local_state = self.sync_core.prepare_sync_data()
            local_base_version = self.sync_core.get_base_version()
            print(f"本地文件数量: {len(local_state)}")
            print(f"本地基准版本: {local_base_version}")
            
            # 发送同步请求
            sync_request = {
                'mode': 'push',
                'client_state': local_state,
                'base_version': local_base_version,
                'client_id': self.sync_core.hasher.client_id
            }
            
            request_data = json.dumps(sync_request).encode('utf-8')
            msg = SyncProtocol.pack_message(SyncProtocol.CMD_SYNC_REQUEST, request_data)
            self.socket.sendall(msg)
            
            # 接收服务端响应
            cmd, data = SyncProtocol.unpack_message(self.socket)
            
            if cmd == SyncProtocol.CMD_CONFLICT:
                # 服务端检测到版本冲突
                conflict_info = json.loads(data.decode('utf-8'))
                print(f"\n[冲突] 服务端版本已更新")
                print(f"  您的基准版本: {local_base_version}")
                print(f"  服务端当前版本: {conflict_info.get('server_version', '?')}")
                print(f"  冲突文件: {conflict_info.get('conflicts', [])}")
                
                if self.conflict_strategy == 'skip':
                    print("根据配置策略，跳过此次推送")
                    return False
                elif self.conflict_strategy == 'local':
                    print("根据配置策略，强制使用本地版本...")
                    return self._force_push()
                else:
                    print("\n建议先执行 pull 获取最新版本，解决冲突后再 push")
                    return False
            
            if cmd != SyncProtocol.CMD_OK:
                print(f"服务端拒绝同步请求: {cmd}")
                return False
            
            sync_plan = json.loads(data.decode('utf-8'))
            server_version = sync_plan.get('server_version', 0)
            files_to_upload = sync_plan.get('files_to_upload', [])
            files_to_delete = sync_plan.get('files_to_delete', [])
            
            print(f"\n同步计划:")
            print(f"  - 上传文件: {len(files_to_upload)}")
            print(f"  - 删除远程文件: {len(files_to_delete)}")
            
            # 上传文件
            upload_success = 0
            for file_path in files_to_upload:
                print(f"\n上传: {file_path}")
                if self.sync_core.send_file(self.socket, file_path):
                    upload_success += 1
            
            # 删除远程文件
            delete_success = 0
            for file_path in files_to_delete:
                print(f"\n删除远程: {file_path}")
                if self.sync_core.send_delete_request(self.socket, file_path):
                    delete_success += 1
            
            # 发送同步完成信号
            complete_data = json.dumps({
                'uploaded': upload_success,
                'deleted': delete_success
            }).encode('utf-8')
            msg = SyncProtocol.pack_message(SyncProtocol.CMD_SYNC_COMPLETE, complete_data)
            self.socket.sendall(msg)
            
            # 接收新版本号
            cmd, data = SyncProtocol.unpack_message(self.socket)
            if cmd == SyncProtocol.CMD_OK:
                result = json.loads(data.decode('utf-8'))
                new_version = result.get('new_version', server_version)
                
                # 更新本地状态
                self.sync_core.update_after_sync(new_version)
                
                print(f"\n推送完成!")
                print(f"  上传成功: {upload_success}/{len(files_to_upload)}")
                print(f"  删除成功: {delete_success}/{len(files_to_delete)}")
                print(f"  新版本号: {new_version}")
                return True
            
            return False
            
        except Exception as e:
            print(f"推送失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _force_push(self) -> bool:
        """强制推送（忽略冲突）"""
        # TODO: 实现强制推送逻辑
        print("强制推送功能尚未实现")
        return False
    
    def pull_from_server(self) -> bool:
        """
        从服务端拉取变更
        
        实现逻辑：
        1. 获取服务端当前状态
        2. 比较本地状态和服务端状态
        3. 下载服务端的新文件/更新的文件
        4. 删除服务端已删除的本地文件
        """
        try:
            print("\n" + "="*50)
            print("开始从服务端拉取...")
            print("="*50)
            
            if not self.socket:
                raise Exception("未连接到服务端")
            
            # 获取本地状态
            local_state = self.sync_core.prepare_sync_data()
            local_base_version = self.sync_core.get_base_version()
            print(f"本地文件数量: {len(local_state)}")
            print(f"本地基准版本: {local_base_version}")
            
            # 发送同步请求
            sync_request = {
                'mode': 'pull',
                'client_state': local_state,
                'base_version': local_base_version,
                'client_id': self.sync_core.hasher.client_id
            }
            
            request_data = json.dumps(sync_request).encode('utf-8')
            msg = SyncProtocol.pack_message(SyncProtocol.CMD_SYNC_REQUEST, request_data)
            self.socket.sendall(msg)
            
            # 接收服务端响应
            cmd, data = SyncProtocol.unpack_message(self.socket)
            
            if cmd != SyncProtocol.CMD_OK:
                print(f"服务端拒绝同步请求: {cmd}")
                return False
            
            sync_plan = json.loads(data.decode('utf-8'))
            server_version = sync_plan.get('server_version', 0)
            files_to_download = sync_plan.get('files_to_download', [])
            files_to_delete = sync_plan.get('files_to_delete', [])
            
            print(f"\n同步计划:")
            print(f"  - 下载文件: {len(files_to_download)}")
            print(f"  - 删除本地文件: {len(files_to_delete)}")
            
            # 接收文件
            download_success = 0
            for file_path in files_to_download:
                print(f"\n等待接收: {file_path}")
                try:
                    cmd, data = SyncProtocol.unpack_message(self.socket)
                    if cmd == SyncProtocol.CMD_FILE_DATA:
                        file_info = json.loads(data.decode('utf-8'))
                        if self.sync_core.receive_file(self.socket, file_info):
                            download_success += 1
                    else:
                        print(f"收到意外命令: {cmd}")
                except Exception as e:
                    print(f"接收文件失败: {e}")
            
            # 删除本地文件
            delete_success = 0
            for file_path in files_to_delete:
                print(f"\n删除本地: {file_path}")
                if self.sync_core.delete_file(file_path):
                    delete_success += 1
            
            # 更新本地状态
            self.sync_core.update_after_sync(server_version)
            
            print(f"\n拉取完成!")
            print(f"  下载成功: {download_success}/{len(files_to_download)}")
            print(f"  删除成功: {delete_success}/{len(files_to_delete)}")
            print(f"  当前版本: {server_version}")
            return True
            
        except Exception as e:
            print(f"拉取失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def sync_with_server(self, mode: str, server_host: str, server_port: int) -> bool:
        """
        与服务端同步
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
        
        has_changes = False
        for change_type, files in changes.items():
            if files and change_type != 'unchanged':
                has_changes = True
                print(f"\n{change_type.upper()}:")
                for file_path in files:
                    print(f"  {file_path}")
        
        if not has_changes:
            print("没有检测到变化")
    
    def show_status(self):
        """显示同步状态"""
        print("\n同步状态:")
        state = self.sync_core.hasher.sync_state
        print(f"  客户端ID: {state.client_id}")
        print(f"  基准版本: {state.base_version}")
        print(f"  上次同步: {state.last_sync_time or '从未同步'}")
        
        changes = self.sync_core.hasher.get_local_changes()
        print(f"\n本地变更:")
        print(f"  新增: {len(changes['added'])} 个文件")
        print(f"  修改: {len(changes['modified'])} 个文件")
        print(f"  删除: {len(changes['deleted'])} 个文件")


def parse_server_address(server_str: str) -> tuple:
    """解析服务端地址"""
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
    parser = argparse.ArgumentParser(description='文件同步客户端 v2.0')
    parser.add_argument('--config', '-c', help='配置文件路径')
    parser.add_argument('--mode', choices=['push', 'pull', 'list', 'changes', 'status'], 
                       default='list', help='操作模式')
    parser.add_argument('--local-dir', help='本地同步目录（覆盖配置文件）')
    parser.add_argument('--sync-json', help='同步状态文件（覆盖配置文件）')
    parser.add_argument('--server', help='服务端地址（覆盖配置文件）')
    parser.add_argument('--conflict', choices=['ask', 'local', 'remote', 'skip'],
                       default='ask', help='冲突处理策略')
    
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
    if args.conflict:
        config_manager.config['client']['conflict_strategy'] = args.conflict
    
    # 验证配置
    if not config_manager.validate_config(for_server=False):
        print("配置验证失败，退出")
        return
    
    client = SyncClient(config_manager)
    
    if args.mode == 'list':
        client.list_local_files()
    elif args.mode == 'changes':
        client.show_changes()
    elif args.mode == 'status':
        client.show_status()
    elif args.mode in ['push', 'pull']:
        try:
            server_address = client.server_address
            host, port = parse_server_address(server_address)
            
            if client.progress_manager:
                local_state = client.sync_core.prepare_sync_data()
                client.progress_manager.start_overall_progress(
                    len(local_state), 
                    f"{args.mode.upper()} 同步"
                )
            
            success = client.sync_with_server(args.mode, host, port)
            
            if client.progress_manager:
                client.progress_manager.finish_overall_progress()
            
            if success:
                print(f"\n{args.mode} 操作完成")
                sys.exit(0)
            else:
                print(f"\n{args.mode} 操作失败")
                sys.exit(1)
        except ValueError as e:
            print(f"错误: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"同步过程中发生错误: {e}")
            import traceback
            traceback.print_exc()
            if client.progress_manager:
                client.progress_manager.finish_overall_progress()
            sys.exit(1)
    else:
        print(f"不支持的操作模式: {args.mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
