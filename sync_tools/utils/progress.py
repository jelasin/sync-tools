#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进度条模块
提供文件传输进度显示功能

优化特性:
1. 美观的视觉效果（颜色、图标）
2. 丰富的信息显示（速度、预计剩余时间）
3. 无 tqdm 时的优雅降级
4. Windows 控制台兼容性
5. 双层进度显示（总体 + 当前文件）
"""

import os
import sys
import time
import shutil
from typing import Optional, Callable, Any

# Windows 终端颜色支持
if sys.platform == 'win32':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

# 尝试导入 tqdm
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False


# ANSI 颜色代码
class Colors:
    """终端颜色"""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    
    # 前景色
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    GRAY = '\033[90m'
    
    @staticmethod
    def supports_color() -> bool:
        """检测终端是否支持颜色"""
        if os.environ.get('NO_COLOR'):
            return False
        if os.environ.get('FORCE_COLOR'):
            return True
        if not hasattr(sys.stdout, 'isatty'):
            return False
        if not sys.stdout.isatty():
            return False
        if sys.platform == 'win32':
            return True  # Windows 10+ 支持 ANSI
        return True


# 进度条字符
class ProgressChars:
    """进度条字符集"""
    # 精细块字符（Unicode）
    BLOCKS = ['', '▏', '▎', '▍', '▌', '▋', '▊', '▉', '█']
    FULL_BLOCK = '█'
    EMPTY_BLOCK = '░'
    
    # ASCII 兼容
    ASCII_FULL = '#'
    ASCII_EMPTY = '-'
    ASCII_EDGE_L = '['
    ASCII_EDGE_R = ']'
    
    # 状态图标
    ICON_FILE = '📄'
    ICON_FOLDER = '📁'
    ICON_UPLOAD = '⬆'
    ICON_DOWNLOAD = '⬇'
    ICON_SYNC = '🔄'
    ICON_SUCCESS = '✓'
    ICON_ERROR = '✗'
    ICON_PROGRESS = '●'
    
    # ASCII 图标
    ASCII_FILE = '[F]'
    ASCII_UPLOAD = '[^]'
    ASCII_DOWNLOAD = '[v]'
    ASCII_SUCCESS = '[OK]'
    ASCII_ERROR = '[X]'
    ASCII_PROGRESS = '>'


def format_size(size: float) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(size) < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}PB"


def format_time(seconds: float) -> str:
    """格式化时间"""
    if seconds < 0:
        return "--:--"
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m{s:02d}s"
    else:
        h, remainder = divmod(int(seconds), 3600)
        m, s = divmod(remainder, 60)
        return f"{h}h{m:02d}m"


def format_speed(bytes_per_second: float) -> str:
    """格式化传输速度"""
    if bytes_per_second < 0:
        return "-- B/s"
    return f"{format_size(bytes_per_second)}/s"


def get_terminal_width() -> int:
    """获取终端宽度"""
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 80


class TextProgressBar:
    """纯文本进度条（无 tqdm 依赖）"""
    
    def __init__(self, total: int, desc: str = "", unit: str = "B",
                 unit_scale: bool = True, disable: bool = False,
                 bar_width: int = 30, use_color: bool = True,
                 use_unicode: bool = True):
        """
        初始化纯文本进度条
        
        Args:
            total: 总数量
            desc: 描述信息
            unit: 单位
            unit_scale: 是否自动缩放单位
            disable: 是否禁用进度条
            bar_width: 进度条宽度
            use_color: 是否使用颜色
            use_unicode: 是否使用 Unicode 字符
        """
        self.total = total
        self.desc = desc
        self.unit = unit
        self.unit_scale = unit_scale
        self.disable = disable
        self.bar_width = bar_width
        self.use_color = use_color and Colors.supports_color()
        self.use_unicode = use_unicode
        
        self.current = 0
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self.last_current = 0
        self.smoothed_speed = 0
        
        # 首次显示
        if not self.disable:
            self._render()
    
    def _get_bar_chars(self) -> tuple:
        """获取进度条字符"""
        if self.use_unicode:
            return (ProgressChars.FULL_BLOCK, ProgressChars.EMPTY_BLOCK, 
                    ProgressChars.BLOCKS, '', '')
        else:
            return (ProgressChars.ASCII_FULL, ProgressChars.ASCII_EMPTY,
                    None, ProgressChars.ASCII_EDGE_L, ProgressChars.ASCII_EDGE_R)
    
    def _colorize(self, text: str, color: str) -> str:
        """添加颜色"""
        if self.use_color:
            return f"{color}{text}{Colors.RESET}"
        return text
    
    def _format_value(self, value: float) -> str:
        """格式化数值"""
        if self.unit == "B" and self.unit_scale:
            return format_size(value)
        elif self.unit_scale and value >= 1000:
            return f"{value/1000:.1f}k"
        else:
            return str(int(value))
    
    def _render(self):
        """渲染进度条"""
        if self.disable:
            return
        
        # 计算进度
        if self.total > 0:
            fraction = min(1.0, self.current / self.total)
            percent = fraction * 100
        else:
            fraction = 0
            percent = 0
        
        # 计算速度
        elapsed = time.time() - self.start_time
        if elapsed > 0:
            instant_speed = self.current / elapsed
            # 平滑速度计算
            if self.smoothed_speed == 0:
                self.smoothed_speed = instant_speed
            else:
                self.smoothed_speed = 0.7 * self.smoothed_speed + 0.3 * instant_speed
        else:
            instant_speed = 0
        
        # 计算剩余时间
        if self.smoothed_speed > 0 and self.total > 0:
            remaining = (self.total - self.current) / self.smoothed_speed
            eta_str = format_time(remaining)
        else:
            eta_str = "--:--"
        
        # 构建进度条
        full_char, empty_char, blocks, edge_l, edge_r = self._get_bar_chars()
        filled_width = int(self.bar_width * fraction)
        
        if blocks:
            # 使用精细块字符
            remainder = (self.bar_width * fraction) - filled_width
            partial_idx = int(remainder * (len(blocks) - 1))
            partial_char = blocks[partial_idx] if partial_idx > 0 else ''
            empty_width = self.bar_width - filled_width - (1 if partial_char else 0)
            bar = full_char * filled_width + partial_char + empty_char * empty_width
        else:
            # ASCII 模式
            bar = full_char * filled_width + empty_char * (self.bar_width - filled_width)
        
        # 颜色化进度条
        if self.use_color:
            if fraction >= 1.0:
                bar_color = Colors.GREEN
            elif fraction >= 0.5:
                bar_color = Colors.CYAN
            else:
                bar_color = Colors.BLUE
            bar = self._colorize(bar, bar_color)
        
        # 构建状态信息
        current_str = self._format_value(self.current)
        total_str = self._format_value(self.total)
        speed_str = format_speed(self.smoothed_speed) if self.unit == "B" and self.unit_scale else ""
        
        # 描述（截断过长的描述）
        max_desc_len = 20
        desc = self.desc[:max_desc_len] + '...' if len(self.desc) > max_desc_len else self.desc
        desc = desc.ljust(max_desc_len + 3)
        
        # 组装输出
        if self.unit == "B" and self.unit_scale:
            status = f"{current_str}/{total_str} {speed_str} ETA:{eta_str}"
        else:
            status = f"{self.current}/{self.total} {self.unit}"
        
        # 百分比颜色
        percent_str = f"{percent:5.1f}%"
        if self.use_color:
            if percent >= 100:
                percent_str = self._colorize(percent_str, Colors.GREEN + Colors.BOLD)
            elif percent >= 50:
                percent_str = self._colorize(percent_str, Colors.CYAN)
        
        output = f"\r{desc} {edge_l}{bar}{edge_r} {percent_str} {status}"
        
        # 清除行尾
        terminal_width = get_terminal_width()
        padding = max(0, terminal_width - len(output.replace('\033[0m', '').replace('\033[', '')) - 5)
        output += ' ' * padding
        
        sys.stdout.write(output)
        sys.stdout.flush()
    
    def update(self, n: int = 1):
        """更新进度"""
        self.current += n
        
        # 限制更新频率（至少 50ms 间隔）
        current_time = time.time()
        if current_time - self.last_update_time >= 0.05 or self.current >= self.total:
            self._render()
            self.last_update_time = current_time
            self.last_current = self.current
    
    def set_description(self, desc: str):
        """设置描述信息"""
        self.desc = desc
        self._render()
    
    def close(self):
        """关闭进度条"""
        if not self.disable:
            self._render()
            elapsed = time.time() - self.start_time
            
            # 完成标记
            if self.use_color:
                if self.current >= self.total:
                    icon = self._colorize("✓", Colors.GREEN + Colors.BOLD)
                else:
                    icon = self._colorize("✗", Colors.RED)
            else:
                icon = "[OK]" if self.current >= self.total else "[X]"
            
            avg_speed = self.current / elapsed if elapsed > 0 else 0
            print(f" {icon} {format_time(elapsed)} @ {format_speed(avg_speed)}")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class ProgressBar:
    """进度条包装类（自动选择 tqdm 或纯文本）"""
    
    def __init__(self, total: int, desc: str = "", unit: str = "B", 
                 unit_scale: bool = True, disable: bool = False,
                 use_tqdm: bool = True, ncols: Optional[int] = None,
                 leave: bool = True, position: Optional[int] = None):
        """
        初始化进度条
        
        Args:
            total: 总数量
            desc: 描述信息
            unit: 单位
            unit_scale: 是否自动缩放单位
            disable: 是否禁用进度条
            use_tqdm: 是否优先使用 tqdm（如果可用）
            ncols: 进度条宽度（None 表示自动）
            leave: 完成后是否保留进度条
            position: 进度条位置（用于多进度条）
        """
        self.total = total
        self.desc = desc
        self.disable = disable
        self.current = 0
        
        # 决定使用哪种进度条
        use_native_tqdm = TQDM_AVAILABLE and use_tqdm and not disable
        
        if use_native_tqdm:
            # 使用 tqdm
            bar_format = '{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'
            self.pbar = tqdm(
                total=total,
                desc=desc,
                unit=unit,
                unit_scale=unit_scale,
                unit_divisor=1024 if unit == "B" else 1000,
                ncols=ncols or min(100, get_terminal_width() - 5),
                leave=leave,
                position=position,
                bar_format=bar_format,
                colour='cyan'  # tqdm 4.64+ 支持
            )
            self._use_text = False
        elif not disable:
            # 使用纯文本进度条
            self.pbar = TextProgressBar(
                total=total,
                desc=desc,
                unit=unit,
                unit_scale=unit_scale,
                disable=disable,
                bar_width=30
            )
            self._use_text = True
        else:
            self.pbar = None
            self._use_text = False
    
    def update(self, n: int = 1):
        """更新进度"""
        self.current += n
        if self.pbar:
            self.pbar.update(n)
    
    def set_description(self, desc: str):
        """设置描述信息"""
        self.desc = desc
        if self.pbar:
            self.pbar.set_description(desc)
    
    def close(self):
        """关闭进度条"""
        if self.pbar:
            self.pbar.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class FileTransferProgress:
    """文件传输进度管理类"""
    
    def __init__(self, show_progress: bool = True, style: str = "bar"):
        """
        初始化文件传输进度管理器
        
        Args:
            show_progress: 是否显示进度
            style: 进度条样式 ('bar', 'text', 'silent', 'simple')
        """
        self.show_progress = show_progress
        self.style = style
        self.current_file_progress = None
        self.overall_progress = None
        
        # 统计信息
        self.total_bytes = 0
        self.transferred_bytes = 0
        self.files_completed = 0
        self.total_files = 0
        self.start_time = None
    
    def start_overall_progress(self, total_files: int, desc: str = "同步进度"):
        """开始总体进度跟踪"""
        self.total_files = total_files
        self.files_completed = 0
        self.start_time = time.time()
        
        if self.show_progress and self.style not in ("silent",):
            use_tqdm = (self.style == "bar")
            self.overall_progress = ProgressBar(
                total=total_files,
                desc=f"📁 {desc}" if Colors.supports_color() else desc,
                unit="文件",
                unit_scale=False,
                use_tqdm=use_tqdm,
                leave=True
            )
    
    def start_file_progress(self, file_size: int, filename: str):
        """开始单个文件进度跟踪"""
        self.total_bytes += file_size
        
        # 截断过长文件名
        display_name = filename
        if len(filename) > 25:
            display_name = "..." + filename[-22:]
        
        if self.show_progress and self.style == "bar":
            self.current_file_progress = ProgressBar(
                total=file_size,
                desc=f"  📄 {display_name}" if Colors.supports_color() else f"  {display_name}",
                unit="B",
                unit_scale=True,
                leave=False,
                position=1 if self.overall_progress else 0
            )
        elif self.show_progress and self.style == "text":
            size_str = format_size(file_size)
            print(f"  → {filename} ({size_str})")
        elif self.show_progress and self.style == "simple":
            print(f"  传输: {filename}", end="", flush=True)
    
    def update_file_progress(self, bytes_transferred: int):
        """更新文件传输进度"""
        self.transferred_bytes += bytes_transferred
        if self.current_file_progress:
            self.current_file_progress.update(bytes_transferred)
    
    def finish_file_progress(self):
        """结束当前文件进度跟踪"""
        if self.current_file_progress:
            self.current_file_progress.close()
            self.current_file_progress = None
        elif self.show_progress and self.style == "simple":
            print(" ✓" if Colors.supports_color() else " [OK]")
    
    def update_overall_progress(self, files_completed: int = 1):
        """更新总体进度"""
        self.files_completed += files_completed
        if self.overall_progress:
            self.overall_progress.update(files_completed)
    
    def finish_overall_progress(self):
        """结束总体进度跟踪"""
        if self.overall_progress:
            self.overall_progress.close()
            self.overall_progress = None
        
        # 显示总结
        if self.show_progress and self.start_time:
            elapsed = time.time() - self.start_time
            if elapsed > 0 and self.transferred_bytes > 0:
                avg_speed = self.transferred_bytes / elapsed
                total_size = format_size(self.transferred_bytes)
                speed_str = format_speed(avg_speed)
                time_str = format_time(elapsed)
                
                if Colors.supports_color():
                    summary = (f"\n{Colors.GREEN}{Colors.BOLD}✓ 同步完成{Colors.RESET} "
                              f"| {self.files_completed}/{self.total_files} 文件 "
                              f"| {total_size} "
                              f"| {time_str} "
                              f"| 平均 {speed_str}")
                else:
                    summary = (f"\n[OK] 同步完成 "
                              f"| {self.files_completed}/{self.total_files} 文件 "
                              f"| {total_size} "
                              f"| {time_str} "
                              f"| 平均 {speed_str}")
                print(summary)
    
    def set_file_description(self, desc: str):
        """设置当前文件描述"""
        if self.current_file_progress:
            self.current_file_progress.set_description(desc)
    
    def set_overall_description(self, desc: str):
        """设置总体描述"""
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
        self.last_update_time = 0
        self.last_bytes = 0
        self.smoothed_speed = 0
    
    def start(self, total_size: int, filename: str):
        """开始传输"""
        self.start_time = time.time()
        self.bytes_transferred = 0
        self.last_update_time = self.start_time
        self.last_bytes = 0
        self.smoothed_speed = 0
        self.progress_manager.start_file_progress(total_size, filename)
    
    def update(self, chunk_size: int):
        """更新进度"""
        self.bytes_transferred += chunk_size
        self.progress_manager.update_file_progress(chunk_size)
        
        # 计算实时速度（每 200ms 更新一次描述）
        current_time = time.time()
        if current_time - self.last_update_time >= 0.2:
            if self.start_time is not None:
                elapsed = current_time - self.start_time
                if elapsed > 0:
                    instant_speed = (self.bytes_transferred - self.last_bytes) / (current_time - self.last_update_time)
                    
                    # 平滑处理
                if self.smoothed_speed == 0:
                    self.smoothed_speed = instant_speed
                else:
                    self.smoothed_speed = 0.6 * self.smoothed_speed + 0.4 * instant_speed
                
                speed_str = format_speed(self.smoothed_speed)
                
                # 更新描述（显示操作类型和速度）
                icon = "⬆" if self.operation == "发送" else "⬇"
                if Colors.supports_color():
                    self.progress_manager.set_file_description(
                        f"  {icon} {self.operation} @ {speed_str}"
                    )
                else:
                    self.progress_manager.set_file_description(
                        f"  {self.operation} @ {speed_str}"
                    )
            
            self.last_update_time = current_time
            self.last_bytes = self.bytes_transferred
    
    def finish(self, success: bool = True):
        """完成传输"""
        self.progress_manager.finish_file_progress()
        if success:
            self.progress_manager.update_overall_progress()


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
    print("=" * 50)
    print("进度条测试")
    print("=" * 50)
    
    # 测试 1: 纯文本进度条
    print("\n[测试 1] 纯文本进度条:")
    with TextProgressBar(100, desc="下载测试", unit="B", unit_scale=True) as pbar:
        for i in range(100):
            pbar.update(1)
            time.sleep(0.02)
    
    # 测试 2: ProgressBar 包装类
    print("\n[测试 2] ProgressBar 包装类:")
    with ProgressBar(1000000, desc="文件传输", unit="B", unit_scale=True) as pbar:
        for i in range(0, 1000000, 8192):
            pbar.update(min(8192, 1000000 - i))
            time.sleep(0.01)
    
    # 测试 3: 完整文件传输进度
    print("\n[测试 3] 完整文件传输场景:")
    progress_manager = FileTransferProgress(True, "bar")
    progress_manager.start_overall_progress(3, "测试传输")
    
    for i in range(3):
        filename = f"test_file_{i+1}.txt"
        file_size = 500000 * (i + 1)  # 递增的文件大小
        
        callback = ProgressCallback(progress_manager, "发送")
        callback.start(file_size, filename)
        
        for chunk_start in range(0, file_size, 8192):
            chunk_size = min(8192, file_size - chunk_start)
            callback.update(chunk_size)
            time.sleep(0.005)
        
        callback.finish(True)
    
    progress_manager.finish_overall_progress()
    
    # 测试 4: 简单模式
    print("\n[测试 4] 简单模式 (simple):")
    progress_manager = FileTransferProgress(True, "simple")
    progress_manager.start_overall_progress(2, "简单测试")
    
    for i in range(2):
        progress_manager.start_file_progress(10000, f"simple_test_{i+1}.dat")
        time.sleep(0.3)
        progress_manager.finish_file_progress()
        progress_manager.update_overall_progress()
    
    progress_manager.finish_overall_progress()
    
    print("\n" + "=" * 50)
    print("所有测试完成!")
    print("=" * 50)


if __name__ == "__main__":
    test_progress()
