#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
处理配置文件读取和验证
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional


class ConfigManager:
    """配置管理类"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            config_path: 配置文件路径，如果为None则使用默认配置
        """
        self.config_path = config_path
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """
        加载配置文件
        
        Returns:
            配置字典
        """
        if self.config_path and Path(self.config_path).exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                print(f"已加载配置文件: {self.config_path}")
                return config
            except (json.JSONDecodeError, IOError) as e:
                print(f"加载配置文件失败: {e}")
                print("使用默认配置")
        
        # 返回默认配置
        return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """
        获取默认配置
        
        Returns:
            默认配置字典
        """
        return {
            "server": {
                "host": "0.0.0.0",
                "port": 8888,
                "sync_dir": "./server_files",
                "sync_json": "./server_sync_state.json",
                "max_connections": 10,
                "encryption": {
                    "enabled": False,
                    "key_file": "./server.key",
                    "algorithm": "AES-256-GCM"
                }
            },
            "client": {
                "local_dir": "./client_files",
                "sync_json": "./client_sync_state.json",
                "server_address": "127.0.0.1:8888",
                "timeout": 30,
                "retry_count": 3,
                "encryption": {
                    "enabled": False,
                    "key_file": "./client.key",
                    "algorithm": "AES-256-GCM"
                },
                "ui": {
                    "show_progress": True,
                    "progress_style": "bar"
                }
            },
            "sync": {
                "exclude_patterns": [
                    "*.tmp", 
                    "*.log", 
                    ".git/*",
                    "__pycache__/*",
                    "*.pyc"
                ],
                "include_hidden": False,
                "compression": False,
                "chunk_size": 8192
            }
        }
    
    def get_server_config(self) -> Dict[str, Any]:
        """
        获取服务端配置
        
        Returns:
            服务端配置字典
        """
        return self.config.get("server", {})
    
    def get_client_config(self) -> Dict[str, Any]:
        """
        获取客户端配置
        
        Returns:
            客户端配置字典
        """
        return self.config.get("client", {})
    
    def get_sync_config(self) -> Dict[str, Any]:
        """
        获取同步配置
        
        Returns:
            同步配置字典
        """
        return self.config.get("sync", {})
    
    def is_encryption_enabled(self, role: str) -> bool:
        """
        检查是否启用加密
        
        Args:
            role: 角色，'server' 或 'client'
            
        Returns:
            是否启用加密
        """
        role_config = self.config.get(role, {})
        encryption_config = role_config.get("encryption", {})
        return encryption_config.get("enabled", False)
    
    def get_encryption_config(self, role: str) -> Dict[str, Any]:
        """
        获取加密配置
        
        Args:
            role: 角色，'server' 或 'client'
            
        Returns:
            加密配置字典
        """
        role_config = self.config.get(role, {})
        return role_config.get("encryption", {})
    
    def get_progress_config(self) -> Dict[str, Any]:
        """
        获取进度条配置
        
        Returns:
            进度条配置字典
        """
        client_config = self.get_client_config()
        return client_config.get("ui", {})
    
    def validate_config(self, for_server: bool = True) -> bool:
        """
        验证配置文件有效性
        
        Args:
            for_server: 是否为服务端验证（True为服务端，False为客户端）
            
        Returns:
            配置是否有效
        """
        # 基础必需节
        required_sections = ["sync"]
        
        # 根据用途添加特定节
        if for_server:
            required_sections.append("server")
        else:
            required_sections.append("client")
        
        for section in required_sections:
            if section not in self.config:
                print(f"配置文件缺少必需的节: {section}")
                return False
        
        # 验证服务端配置
        if for_server and "server" in self.config:
            server_config = self.get_server_config()
            required_server_keys = ["host", "port", "sync_dir", "sync_json"]
            for key in required_server_keys:
                if key not in server_config:
                    print(f"服务端配置缺少必需的键: {key}")
                    return False
                    
            # 验证端口号
            port = server_config.get("port")
            if not isinstance(port, int) or port < 1 or port > 65535:
                print(f"无效的端口号: {port}")
                return False
        
        # 验证客户端配置
        if not for_server and "client" in self.config:
            client_config = self.get_client_config()
            required_client_keys = ["local_dir", "sync_json", "server_address"]
            for key in required_client_keys:
                if key not in client_config:
                    print(f"客户端配置缺少必需的键: {key}")
                    return False

        print("配置文件验证通过")
        return True
    
    def save_config(self, output_path: Optional[str] = None) -> bool:
        """
        保存配置到文件
        
        Args:
            output_path: 输出文件路径，如果为None则使用原路径
            
        Returns:
            保存是否成功
        """
        save_path = output_path or self.config_path or "config.json"
        
        try:
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            print(f"配置已保存到: {save_path}")
            return True
        except (IOError, OSError) as e:
            print(f"保存配置文件失败: {e}")
            return False
    
    def create_sample_config(self, output_path: str = "config.json") -> bool:
        """
        创建示例配置文件
        
        Args:
            output_path: 输出文件路径
            
        Returns:
            创建是否成功
        """
        try:
            sample_config = self._get_default_config()
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(sample_config, f, indent=2, ensure_ascii=False)
            print(f"示例配置文件已创建: {output_path}")
            return True
        except (IOError, OSError) as e:
            print(f"创建示例配置文件失败: {e}")
            return False


def create_default_config():
    """创建默认配置文件的命令行工具"""
    import argparse
    
    parser = argparse.ArgumentParser(description='创建默认配置文件')
    parser.add_argument('--output', '-o', default='config.json', help='输出文件路径')
    
    args = parser.parse_args()
    
    config_manager = ConfigManager()
    if config_manager.create_sample_config(args.output):
        print("默认配置文件创建成功")
    else:
        print("默认配置文件创建失败")


if __name__ == "__main__":
    create_default_config()
