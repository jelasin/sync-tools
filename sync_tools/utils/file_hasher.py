#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件hash计算工具
用于计算文件的MD5值和管理文件状态
"""

import hashlib
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Set


class FileHasher:
    """文件hash计算和管理类"""
    
    def __init__(self, base_dir: str, hash_file: Optional[str] = None):
        """
        初始化FileHasher
        
        Args:
            base_dir: 基础目录路径
            hash_file: 保存hash状态的文件路径，如果为None则使用默认名称
        """
        self.base_dir = Path(base_dir).resolve()
        if hash_file:
            self.hash_file = Path(hash_file).resolve()
        else:
            self.hash_file = self.base_dir / ".sync_state.json"
        self.file_hashes = {}
        self.load_state()
    
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
        获取相对于基础目录的路径
        
        Args:
            file_path: 文件绝对路径
            
        Returns:
            相对路径字符串
        """
        try:
            return str(file_path.relative_to(self.base_dir))
        except ValueError:
            return str(file_path)
    
    def scan_directory(self) -> Dict[str, Dict]:
        """
        扫描目录并计算所有文件的hash值
        
        Returns:
            包含文件信息的字典
        """
        current_state = {}
        
        if not self.base_dir.exists():
            print(f"目录不存在: {self.base_dir}")
            return current_state
        
        for root, dirs, files in os.walk(self.base_dir):
            root_path = Path(root)
            
            # 跳过隐藏目录和同步状态文件
            if any(part.startswith('.') for part in root_path.parts):
                continue
            
            for file_name in files:
                if file_name.startswith('.'):
                    continue
                
                file_path = root_path / file_name
                relative_path = self.get_relative_path(file_path)
                
                # 跳过hash文件本身
                if file_path == self.hash_file:
                    continue
                
                file_hash = self.calculate_file_hash(file_path)
                if file_hash:
                    current_state[relative_path] = {
                        'hash': file_hash,
                        'size': file_path.stat().st_size,
                        'modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
                        'type': 'file'
                    }
        
        return current_state
    
    def load_state(self) -> Dict[str, Dict]:
        """
        从文件加载之前保存的状态
        
        Returns:
            文件状态字典
        """
        if self.hash_file.exists():
            try:
                with open(self.hash_file, 'r', encoding='utf-8') as f:
                    self.file_hashes = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"加载状态文件失败: {e}")
                self.file_hashes = {}
        else:
            self.file_hashes = {}
        
        return self.file_hashes
    
    def save_state(self, state: Optional[Dict[str, Dict]] = None) -> bool:
        """
        保存当前状态到文件
        
        Args:
            state: 要保存的状态，如果为None则保存当前状态
            
        Returns:
            保存是否成功
        """
        if state is not None:
            self.file_hashes = state
        
        try:
            # 确保目录存在
            self.hash_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.hash_file, 'w', encoding='utf-8') as f:
                json.dump(self.file_hashes, f, indent=2, ensure_ascii=False)
            return True
        except (IOError, OSError) as e:
            print(f"保存状态文件失败: {e}")
            return False
    
    def get_changes(self) -> Dict[str, Dict]:
        """
        获取文件变化情况
        
        Returns:
            包含变化信息的字典
        """
        current_state = self.scan_directory()
        old_state = self.file_hashes
        
        changes = {
            'added': {},      # 新增文件
            'modified': {},   # 修改文件  
            'deleted': {},    # 删除文件
            'unchanged': {}   # 未变化文件
        }
        
        # 检查新增和修改的文件
        for file_path, file_info in current_state.items():
            if file_path not in old_state:
                changes['added'][file_path] = file_info
            elif old_state[file_path]['hash'] != file_info['hash']:
                changes['modified'][file_path] = file_info
            else:
                changes['unchanged'][file_path] = file_info
        
        # 检查删除的文件
        for file_path, file_info in old_state.items():
            if file_path not in current_state:
                changes['deleted'][file_path] = file_info
        
        return changes
    
    def update_state(self):
        """更新状态到最新"""
        current_state = self.scan_directory()
        self.save_state(current_state)
    
    def get_file_list(self) -> Set[str]:
        """
        获取当前所有文件列表
        
        Returns:
            文件路径集合
        """
        current_state = self.scan_directory()
        return set(current_state.keys())


if __name__ == "__main__":
    # 测试代码
    hasher = FileHasher("./test_dir")
    changes = hasher.get_changes()
    print("文件变化:")
    for change_type, files in changes.items():
        if files:
            print(f"{change_type}: {list(files.keys())}")
