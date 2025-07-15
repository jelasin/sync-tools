#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进度条模块
提供文件传输进度显示功能
"""

import time
from typing import Optional, Callable, Any

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    print("警告: tqdm库未安装，进度条功能不可用")
    print("安装命令: pip install tqdm")


class ProgressBar:
    """进度条包装类"""
    
    def __init__(self, total: int, desc: str = "", unit: str = "B", 
                 unit_scale: bool = True, disable: bool = False):
        """
        初始化进度条
        
        Args:
            total: 总数量
            desc: 描述信息
            unit: 单位
            unit_scale: 是否自动缩放单位
            disable: 是否禁用进度条
        """
        self.total = total
        self.desc = desc
        self.disable = disable or not TQDM_AVAILABLE
        self.current = 0
        
        if not self.disable and TQDM_AVAILABLE:
            self.pbar = tqdm(
                total=total,
                desc=desc,
                unit=unit,
                unit_scale=unit_scale,
                unit_divisor=1024 if unit == "B" else 1000
            )
        else:
            self.pbar = None
            if not self.disable:
                print(f"开始: {desc} (总计: {total})")
    
    def update(self, n: int = 1):
        """
        更新进度
        
        Args:
            n: 增加的数量
        """
        self.current += n
        
        if self.pbar:
            self.pbar.update(n)
        elif not self.disable:
            # 简单的文本进度显示
            if self.total > 0:
                progress = (self.current / self.total) * 100
                print(f"\r{self.desc}: {progress:.1f}% ({self.current}/{self.total})", end="", flush=True)
            else:
                print(f"\r{self.desc}: {self.current} items", end="", flush=True)
    
    def set_description(self, desc: str):
        """
        设置描述信息
        
        Args:
            desc: 新的描述信息
        """
        self.desc = desc
        if self.pbar:
            self.pbar.set_description(desc)
    
    def close(self):
        """关闭进度条"""
        if self.pbar:
            self.pbar.close()
        elif not self.disable:
            print()  # 换行
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()


class FileTransferProgress:
    """文件传输进度管理类"""
    
    def __init__(self, show_progress: bool = True, style: str = "bar"):
        """
        初始化文件传输进度管理器
        
        Args:
            show_progress: 是否显示进度
            style: 进度条样式 ('bar', 'text', 'silent')
        """
        self.show_progress = show_progress and TQDM_AVAILABLE
        self.style = style
        self.current_file_progress = None
        self.overall_progress = None
    
    def start_overall_progress(self, total_files: int, desc: str = "同步进度"):
        """
        开始总体进度跟踪
        
        Args:
            total_files: 总文件数
            desc: 描述信息
        """
        if self.show_progress and self.style != "silent":
            disable = (self.style == "text")
            self.overall_progress = ProgressBar(
                total=total_files,
                desc=desc,
                unit="个文件",
                unit_scale=False,
                disable=disable
            )
    
    def start_file_progress(self, file_size: int, filename: str):
        """
        开始单个文件进度跟踪
        
        Args:
            file_size: 文件大小
            filename: 文件名
        """
        if self.show_progress and self.style == "bar":
            self.current_file_progress = ProgressBar(
                total=file_size,
                desc=f"传输 {filename}",
                unit="B",
                unit_scale=True
            )
        elif self.show_progress:
            print(f"传输文件: {filename} ({file_size:,} 字节)")
    
    def update_file_progress(self, bytes_transferred: int):
        """
        更新文件传输进度
        
        Args:
            bytes_transferred: 已传输字节数
        """
        if self.current_file_progress:
            self.current_file_progress.update(bytes_transferred)
    
    def finish_file_progress(self):
        """结束当前文件进度跟踪"""
        if self.current_file_progress:
            self.current_file_progress.close()
            self.current_file_progress = None
    
    def update_overall_progress(self, files_completed: int = 1):
        """
        更新总体进度
        
        Args:
            files_completed: 完成的文件数
        """
        if self.overall_progress:
            self.overall_progress.update(files_completed)
    
    def finish_overall_progress(self):
        """结束总体进度跟踪"""
        if self.overall_progress:
            self.overall_progress.close()
            self.overall_progress = None
    
    def set_file_description(self, desc: str):
        """
        设置当前文件描述
        
        Args:
            desc: 描述信息
        """
        if self.current_file_progress:
            self.current_file_progress.set_description(desc)
    
    def set_overall_description(self, desc: str):
        """
        设置总体描述
        
        Args:
            desc: 描述信息
        """
        if self.overall_progress:
            self.overall_progress.set_description(desc)


class ProgressCallback:
    """进度回调处理器"""
    
    def __init__(self, progress_manager: FileTransferProgress, 
                 operation: str = "传输"):
        """
        初始化进度回调处理器
        
        Args:
            progress_manager: 进度管理器
            operation: 操作类型描述
        """
        self.progress_manager = progress_manager
        self.operation = operation
        self.start_time = None
        self.bytes_transferred = 0
    
    def start(self, total_size: int, filename: str):
        """
        开始传输
        
        Args:
            total_size: 总大小
            filename: 文件名
        """
        self.start_time = time.time()
        self.bytes_transferred = 0
        self.progress_manager.start_file_progress(total_size, filename)
    
    def update(self, chunk_size: int):
        """
        更新进度
        
        Args:
            chunk_size: 本次传输的数据块大小
        """
        self.bytes_transferred += chunk_size
        self.progress_manager.update_file_progress(chunk_size)
        
        # 可以在这里添加速度计算等功能
        if self.start_time:
            elapsed = time.time() - self.start_time
            if elapsed > 0:
                speed = self.bytes_transferred / elapsed
                speed_str = self._format_speed(speed)
                self.progress_manager.set_file_description(
                    f"{self.operation} ({speed_str})"
                )
    
    def finish(self, success: bool = True):
        """
        完成传输
        
        Args:
            success: 是否成功
        """
        self.progress_manager.finish_file_progress()
        if success:
            self.progress_manager.update_overall_progress()
    
    def _format_speed(self, bytes_per_second: float) -> str:
        """
        格式化传输速度
        
        Args:
            bytes_per_second: 每秒字节数
            
        Returns:
            格式化的速度字符串
        """
        if bytes_per_second < 1024:
            return f"{bytes_per_second:.1f} B/s"
        elif bytes_per_second < 1024 * 1024:
            return f"{bytes_per_second / 1024:.1f} KB/s"
        elif bytes_per_second < 1024 * 1024 * 1024:
            return f"{bytes_per_second / (1024 * 1024):.1f} MB/s"
        else:
            return f"{bytes_per_second / (1024 * 1024 * 1024):.1f} GB/s"


def create_progress_manager(config: dict) -> FileTransferProgress:
    """
    根据配置创建进度管理器
    
    Args:
        config: 进度配置字典
        
    Returns:
        进度管理器实例
    """
    show_progress = config.get("show_progress", True)
    style = config.get("progress_style", "bar")
    
    return FileTransferProgress(show_progress, style)


# 简单的测试函数
def test_progress():
    """测试进度条功能"""
    import time
    
    print("测试进度条功能...")
    
    # 测试总体进度
    progress_manager = FileTransferProgress(True, "bar")
    progress_manager.start_overall_progress(3, "测试传输")
    
    # 测试文件进度
    for i in range(3):
        filename = f"test_file_{i+1}.txt"
        file_size = 1000000  # 1MB
        
        progress_manager.start_file_progress(file_size, filename)
        
        # 模拟文件传输
        for chunk in range(0, file_size, 8192):
            chunk_size = min(8192, file_size - chunk)
            progress_manager.update_file_progress(chunk_size)
            time.sleep(0.01)  # 模拟传输延迟
        
        progress_manager.finish_file_progress()
        progress_manager.update_overall_progress()
    
    progress_manager.finish_overall_progress()
    print("\n测试完成!")


if __name__ == "__main__":
    test_progress()
