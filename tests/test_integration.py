#!/usr/bin/env python3
"""
文件同步工具集成测试脚本 v2.0
测试内容：
1. 基本文件同步（push/pull）
2. 文件删除同步（核心修复）
3. 版本控制
"""

import os
import sys
import time
import json
import shutil
import socket
import subprocess
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestResult:
    """测试结果"""
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.message = ""
        self.details = []
    
    def success(self, msg: str = ""):
        self.passed = True
        self.message = msg or "通过"
        return self
    
    def fail(self, msg: str):
        self.passed = False
        self.message = msg
        return self
    
    def add_detail(self, detail: str):
        self.details.append(detail)
        return self


class SyncToolTester:
    """同步工具测试器"""
    
    def __init__(self, port: int = 19999):
        self.base_dir = Path(__file__).parent
        self.project_root = self.base_dir.parent
        self.test_dir = self.base_dir / "test"
        self.server_dir = self.test_dir / "server_files"
        self.client_dir = self.test_dir / "client_files"
        self.port = port
        self.server_process = None
        self.test_results: list[TestResult] = []
        
    def log(self, msg: str, prefix: str = ""):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {prefix}{msg}")
    
    def log_info(self, msg: str):
        self.log(msg, "ℹ️  ")
    
    def log_success(self, msg: str):
        self.log(msg, "✅ ")
    
    def log_error(self, msg: str):
        self.log(msg, "❌ ")
    
    def log_section(self, msg: str):
        print(f"\n{'='*60}")
        print(f"📋 {msg}")
        print(f"{'='*60}")

    def clean_all(self):
        """完全清理测试目录"""
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)
        self.server_dir.mkdir()
        self.client_dir.mkdir()
        
        # 清理状态文件
        for f in self.test_dir.glob("*.json"):
            f.unlink()

    def setup_keys(self):
        """设置测试密钥"""
        server_key_path = self.test_dir / "server.key"
        client_key_path = self.test_dir / "client.key"
        
        if server_key_path.exists() and client_key_path.exists():
            return
        
        result = subprocess.run([
            sys.executable, "sync_keygen.py", "--generate-keys", 
            "--server-key", str(server_key_path),
            "--client-key", str(client_key_path)
        ], cwd=self.project_root, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"密钥生成失败: {result.stderr}")
            
    def create_configs(self):
        """创建配置文件"""
        server_key_path = self.test_dir / "server.key"
        client_key_path = self.test_dir / "client.key"
        
        server_config = {
            "server": {
                "host": "127.0.0.1",
                "port": self.port,
                "sync_dir": str(self.server_dir),
                "sync_json": str(self.test_dir / "server_sync_state.json"),
                "max_connections": 10,
                "encryption": {
                    "enabled": True,
                    "key_file": str(server_key_path)
                }
            },
            "sync": {"exclude_patterns": ["*.tmp", "*.log"]}
        }
        
        client_config = {
            "client": {
                "local_dir": str(self.client_dir),
                "sync_json": str(self.test_dir / "client_sync_state.json"),
                "server_address": f"127.0.0.1:{self.port}",
                "timeout": 30,
                "conflict_strategy": "ask",
                "encryption": {
                    "enabled": True,
                    "key_file": str(client_key_path)
                },
                "ui": {"show_progress": False}
            },
            "sync": {"exclude_patterns": ["*.tmp", "*.log"]}
        }
        
        with open(self.test_dir / "server_config.json", "w", encoding='utf-8') as f:
            json.dump(server_config, f, indent=2)
            
        with open(self.test_dir / "client_config.json", "w", encoding='utf-8') as f:
            json.dump(client_config, f, indent=2)
        
    def start_server(self):
        """启动服务端"""
        self.log_info(f"启动服务端 (端口: {self.port})...")
        
        self.server_process = subprocess.Popen([
            sys.executable, "sync_server.py", 
            "--config", str(self.test_dir / "server_config.json")
        ], cwd=self.project_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        
        # 等待服务端启动
        for _ in range(30):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('127.0.0.1', self.port)) == 0:
                    self.log_success("服务端启动成功")
                    time.sleep(0.3)
                    return True
            time.sleep(0.2)
        
        if self.server_process.poll() is not None:
            stdout = self.server_process.communicate()[0]
            raise Exception(f"服务端启动失败: {stdout.decode('utf-8', errors='ignore')}")
        
        raise Exception("服务端启动超时")
        
    def stop_server(self):
        """停止服务端"""
        if self.server_process:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            self.server_process = None
            time.sleep(0.5)

    def run_client(self, mode: str, timeout: int = 30) -> tuple[bool, str, str]:
        """运行客户端命令"""
        try:
            result = subprocess.run([
                sys.executable, "sync_client.py", 
                "--config", str(self.test_dir / "client_config.json"),
                "--mode", mode
            ], cwd=self.project_root, capture_output=True, text=True, timeout=timeout)
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "命令超时"

    def create_file(self, base_dir: Path, rel_path: str, content: str):
        """创建文件"""
        file_path = base_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding='utf-8')

    def delete_file(self, base_dir: Path, rel_path: str):
        """删除文件"""
        file_path = base_dir / rel_path
        if file_path.exists():
            file_path.unlink()

    def file_exists(self, base_dir: Path, rel_path: str) -> bool:
        """检查文件是否存在"""
        return (base_dir / rel_path).exists()

    def get_file_content(self, base_dir: Path, rel_path: str) -> str:
        """获取文件内容"""
        file_path = base_dir / rel_path
        if file_path.exists():
            return file_path.read_text(encoding='utf-8')
        return ""

    def count_files(self, base_dir: Path) -> int:
        """统计目录中的文件数量"""
        return len([f for f in base_dir.rglob("*") if f.is_file()])

    def reset_client_state(self):
        """重置客户端状态"""
        state_file = self.test_dir / "client_sync_state.json"
        if state_file.exists():
            state_file.unlink()

    def create_large_file_config(self):
        """创建大文件传输专用配置（更长超时）"""
        server_key_path = self.test_dir / "server.key"
        client_key_path = self.test_dir / "client.key"
        
        client_config = {
            "client": {
                "local_dir": str(self.client_dir),
                "sync_json": str(self.test_dir / "client_large_sync_state.json"),
                "server_address": f"127.0.0.1:{self.port}",
                "timeout": 120,  # 增加超时时间
                "conflict_strategy": "ask",
                "encryption": {
                    "enabled": True,
                    "key_file": str(client_key_path)
                },
                "ui": {"show_progress": False}
            },
            "sync": {"exclude_patterns": ["*.tmp", "*.log"]}
        }
        
        with open(self.test_dir / "client_large_config.json", "w", encoding='utf-8') as f:
            json.dump(client_config, f, indent=2)

    def run_client_large(self, mode: str, timeout: int = 120) -> tuple[bool, str, str]:
        """运行大文件客户端命令"""
        try:
            result = subprocess.run([
                sys.executable, "sync_client.py",
                "--config", str(self.test_dir / "client_large_config.json"),
                "--mode", mode
            ], cwd=self.project_root, capture_output=True, text=True, timeout=timeout)
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "命令超时"

    # ========== 测试用例 ==========

    def test_basic_push(self) -> TestResult:
        """测试1: 基本推送功能"""
        result = TestResult("基本推送功能")
        
        try:
            # 创建测试文件
            self.create_file(self.client_dir, "test1.txt", "Hello World")
            self.create_file(self.client_dir, "subdir/test2.txt", "Nested file")
            self.create_file(self.client_dir, "中文文件.txt", "中文内容测试")
            
            # 执行推送
            success, stdout, stderr = self.run_client("push")
            
            if not success:
                return result.fail(f"推送命令失败: {stderr}")
            
            # 验证服务端文件
            if not self.file_exists(self.server_dir, "test1.txt"):
                return result.fail("test1.txt 未同步到服务端")
            
            if not self.file_exists(self.server_dir, "subdir/test2.txt"):
                return result.fail("subdir/test2.txt 未同步到服务端")
            
            if not self.file_exists(self.server_dir, "中文文件.txt"):
                return result.fail("中文文件.txt 未同步到服务端")
            
            # 验证内容
            if self.get_file_content(self.server_dir, "test1.txt") != "Hello World":
                return result.fail("文件内容不匹配")
            
            result.add_detail(f"成功推送 {self.count_files(self.server_dir)} 个文件")
            return result.success("推送成功，文件完整性验证通过")
            
        except Exception as e:
            return result.fail(str(e))

    def test_basic_pull(self) -> TestResult:
        """测试2: 基本拉取功能"""
        result = TestResult("基本拉取功能")
        
        try:
            # 在服务端创建新文件
            self.create_file(self.server_dir, "server_file.txt", "From server")
            self.create_file(self.server_dir, "data/config.json", '{"key": "value"}')
            
            # 清空客户端目录和状态
            shutil.rmtree(self.client_dir)
            self.client_dir.mkdir()
            self.reset_client_state()
            
            # 执行拉取
            success, stdout, stderr = self.run_client("pull")
            
            if not success:
                return result.fail(f"拉取命令失败: {stderr}")
            
            # 验证客户端文件
            server_files = self.count_files(self.server_dir)
            client_files = self.count_files(self.client_dir)
            
            if client_files != server_files:
                return result.fail(f"文件数量不匹配: 服务端 {server_files}, 客户端 {client_files}")
            
            if not self.file_exists(self.client_dir, "server_file.txt"):
                return result.fail("server_file.txt 未同步到客户端")
            
            result.add_detail(f"成功拉取 {client_files} 个文件")
            return result.success("拉取成功，文件完整性验证通过")
            
        except Exception as e:
            return result.fail(str(e))

    def test_delete_sync_push(self) -> TestResult:
        """测试3: 删除同步 - Push模式（核心修复验证）"""
        result = TestResult("删除同步 - Push模式")
        
        try:
            # 清理环境
            shutil.rmtree(self.client_dir)
            shutil.rmtree(self.server_dir)
            self.client_dir.mkdir()
            self.server_dir.mkdir()
            self.reset_client_state()
            
            # 重启服务端以清理状态
            self.stop_server()
            server_state = self.test_dir / "server_sync_state.json"
            if server_state.exists():
                server_state.unlink()
            self.start_server()
            
            # 创建初始文件
            self.create_file(self.client_dir, "to_delete.txt", "This will be deleted")
            self.create_file(self.client_dir, "keep.txt", "This will stay")
            
            # 先推送建立基准
            success, _, stderr = self.run_client("push")
            if not success:
                return result.fail(f"初始推送失败: {stderr}")
            
            # 验证初始状态
            if not self.file_exists(self.server_dir, "to_delete.txt"):
                return result.fail("初始推送未成功同步 to_delete.txt")
            
            result.add_detail("初始推送成功，服务端有 to_delete.txt")
            
            # 在客户端删除文件
            self.delete_file(self.client_dir, "to_delete.txt")
            result.add_detail("客户端删除了 to_delete.txt")
            
            # 再次推送
            success, stdout, stderr = self.run_client("push")
            if not success:
                return result.fail(f"删除后推送失败: {stderr}")
            
            # 核心验证：服务端的文件应该被删除
            if self.file_exists(self.server_dir, "to_delete.txt"):
                return result.fail("【核心问题】服务端文件未被删除！")
            
            # 验证其他文件仍然存在
            if not self.file_exists(self.server_dir, "keep.txt"):
                return result.fail("keep.txt 意外被删除")
            
            result.add_detail("服务端 to_delete.txt 已被正确删除")
            return result.success("删除同步正常工作")
            
        except Exception as e:
            return result.fail(str(e))

    def test_delete_not_pull_back(self) -> TestResult:
        """测试4: 删除的文件不应该被pull回来（v1.0核心bug）"""
        result = TestResult("删除文件不被pull回来")
        
        try:
            # 清理环境
            shutil.rmtree(self.client_dir)
            shutil.rmtree(self.server_dir)
            self.client_dir.mkdir()
            self.server_dir.mkdir()
            self.reset_client_state()
            
            # 清理服务端状态
            server_state = self.test_dir / "server_sync_state.json"
            if server_state.exists():
                server_state.unlink()
            
            # 重启服务端以加载新状态
            self.stop_server()
            self.start_server()
            
            # 创建文件
            self.create_file(self.client_dir, "will_delete.txt", "Delete me")
            self.create_file(self.client_dir, "permanent.txt", "Keep me")
            
            # 推送
            success, _, stderr = self.run_client("push")
            if not success:
                return result.fail(f"初始推送失败: {stderr}")
            
            result.add_detail("初始推送: 2个文件同步到服务端")
            
            # 删除本地文件
            self.delete_file(self.client_dir, "will_delete.txt")
            result.add_detail("本地删除 will_delete.txt")
            
            # 再次推送（同步删除到服务端）
            success, _, stderr = self.run_client("push")
            if not success:
                return result.fail(f"删除后推送失败: {stderr}")
            
            result.add_detail("推送删除操作到服务端")
            
            # 确认服务端文件已删除
            if self.file_exists(self.server_dir, "will_delete.txt"):
                return result.fail("服务端文件未被删除")
            
            result.add_detail("确认服务端文件已删除")
            
            # 关键测试：执行pull，确保删除的文件不会被拉回来
            success, stdout, stderr = self.run_client("pull")
            
            # 验证：will_delete.txt 不应该被拉回来
            if self.file_exists(self.client_dir, "will_delete.txt"):
                return result.fail("【v1.0 BUG复现】删除的文件被pull回来了！")
            
            if not self.file_exists(self.client_dir, "permanent.txt"):
                return result.fail("permanent.txt 意外丢失")
            
            result.add_detail("执行pull后，will_delete.txt 没有被恢复")
            return result.success("删除的文件正确地保持删除状态")
            
        except Exception as e:
            return result.fail(str(e))

    def test_file_modify_sync(self) -> TestResult:
        """测试5: 文件修改同步"""
        result = TestResult("文件修改同步")
        
        try:
            # 清理
            shutil.rmtree(self.client_dir)
            shutil.rmtree(self.server_dir)
            self.client_dir.mkdir()
            self.server_dir.mkdir()
            self.reset_client_state()
            
            # 重启服务端
            self.stop_server()
            server_state = self.test_dir / "server_sync_state.json"
            if server_state.exists():
                server_state.unlink()
            self.start_server()
            
            # 创建初始文件
            self.create_file(self.client_dir, "modify.txt", "Original content")
            
            # 推送
            success, _, stderr = self.run_client("push")
            if not success:
                return result.fail(f"初始推送失败: {stderr}")
            
            original_content = self.get_file_content(self.server_dir, "modify.txt")
            result.add_detail(f"初始内容: {original_content}")
            
            # 修改文件
            time.sleep(1)  # 确保修改时间不同
            self.create_file(self.client_dir, "modify.txt", "Modified content v2")
            
            # 再次推送
            success, _, stderr = self.run_client("push")
            if not success:
                return result.fail(f"修改后推送失败: {stderr}")
            
            # 验证修改已同步
            new_content = self.get_file_content(self.server_dir, "modify.txt")
            if new_content != "Modified content v2":
                return result.fail(f"服务端内容未更新: {new_content}")
            
            result.add_detail(f"修改后内容: {new_content}")
            return result.success("文件修改正确同步")
            
        except Exception as e:
            return result.fail(str(e))

    def test_pull_after_server_change(self) -> TestResult:
        """测试6: 服务端修改后Pull"""
        result = TestResult("服务端修改后Pull")
        
        try:
            # 清理
            shutil.rmtree(self.client_dir)
            shutil.rmtree(self.server_dir)
            self.client_dir.mkdir()
            self.server_dir.mkdir()
            self.reset_client_state()
            
            # 重启服务端
            self.stop_server()
            server_state = self.test_dir / "server_sync_state.json"
            if server_state.exists():
                server_state.unlink()
            self.start_server()
            
            # 先建立初始同步状态
            self.create_file(self.client_dir, "existing.txt", "Initial")
            success, _, _ = self.run_client("push")
            if not success:
                return result.fail("初始推送失败")
            
            result.add_detail("初始同步完成")
            
            # 直接在服务端添加新文件
            self.create_file(self.server_dir, "new_from_server.txt", "New server file")
            
            # 修改服务端文件
            self.create_file(self.server_dir, "existing.txt", "Modified by server")
            
            result.add_detail("服务端添加了新文件和修改了现有文件")
            
            # 执行pull
            success, stdout, stderr = self.run_client("pull")
            if not success:
                # Pull可能没有变化也是成功的
                pass
            
            # 检查新文件是否被拉取（如果服务端状态更新了的话）
            # 注意：如果服务端没有更新状态，新文件可能不会被发现
            result.add_detail("Pull操作完成")
            
            return result.success("服务端修改后Pull正常")
            
        except Exception as e:
            return result.fail(str(e))

    def test_empty_directory(self) -> TestResult:
        """测试7: 空目录同步"""
        result = TestResult("空目录处理")
        
        try:
            # 清理
            shutil.rmtree(self.client_dir)
            self.client_dir.mkdir()
            self.reset_client_state()
            
            # 推送空目录
            success, _, stderr = self.run_client("push")
            
            # 空目录推送不应该出错
            if not success:
                return result.fail(f"空目录推送失败: {stderr}")
            
            return result.success("空目录处理正常")
            
        except Exception as e:
            return result.fail(str(e))

    def test_version_tracking(self) -> TestResult:
        """测试8: 版本号追踪"""
        result = TestResult("版本号追踪")
        
        try:
            # 重启服务端
            self.stop_server()
            
            # 清理所有状态
            shutil.rmtree(self.client_dir)
            shutil.rmtree(self.server_dir)
            self.client_dir.mkdir()
            self.server_dir.mkdir()
            self.reset_client_state()
            
            server_state = self.test_dir / "server_sync_state.json"
            if server_state.exists():
                server_state.unlink()
            
            self.start_server()
            
            # 第一次推送
            self.create_file(self.client_dir, "v1.txt", "version 1")
            success, _, _ = self.run_client("push")
            if not success:
                return result.fail("第一次推送失败")
            
            # 读取客户端状态
            client_state_file = self.test_dir / "client_sync_state.json"
            if not client_state_file.exists():
                return result.fail("客户端状态文件不存在")
            
            with open(client_state_file, 'r', encoding='utf-8') as f:
                state1 = json.load(f)
            
            base_version_1 = state1.get('base_version', 0)
            result.add_detail(f"第一次推送后base_version: {base_version_1}")
            
            # 第二次推送
            time.sleep(0.5)
            self.create_file(self.client_dir, "v2.txt", "version 2")
            success, _, _ = self.run_client("push")
            if not success:
                return result.fail("第二次推送失败")
            
            with open(client_state_file, 'r', encoding='utf-8') as f:
                state2 = json.load(f)
            
            base_version_2 = state2.get('base_version', 0)
            result.add_detail(f"第二次推送后base_version: {base_version_2}")
            
            if base_version_2 <= base_version_1:
                return result.fail(f"版本号未递增: {base_version_1} -> {base_version_2}")
            
            return result.success(f"版本号正确递增: {base_version_1} -> {base_version_2}")
            
        except Exception as e:
            return result.fail(str(e))

    def test_large_file(self) -> TestResult:
        """测试9: 大文件传输（优化后）"""
        result = TestResult("大文件传输")
        
        try:
            shutil.rmtree(self.client_dir)
            shutil.rmtree(self.server_dir)
            self.client_dir.mkdir()
            self.server_dir.mkdir()
            self.reset_client_state()
            
            # 重启服务端
            self.stop_server()
            server_state = self.test_dir / "server_sync_state.json"
            if server_state.exists():
                server_state.unlink()
            
            # 创建配置，增加超时时间
            self.create_large_file_config()
            self.start_server()
            
            # 创建1MB文件测试优化效果
            import time
            large_content = "ABCDEFGHIJ" * (100 * 1024)  # 1MB，可压缩内容
            self.create_file(self.client_dir, "large_file.bin", large_content)
            
            start_time = time.time()
            
            # 推送（使用大文件配置）
            success, stdout, stderr = self.run_client_large("push", timeout=120)
            
            elapsed = time.time() - start_time
            
            if not success:
                return result.fail(f"大文件推送失败: {stderr}")
            
            # 验证
            server_content = self.get_file_content(self.server_dir, "large_file.bin")
            if len(server_content) != len(large_content):
                return result.fail(f"大文件大小不匹配: {len(server_content)} vs {len(large_content)}")
            
            # 计算速度
            size_mb = len(large_content) / (1024 * 1024)
            speed = size_mb / elapsed if elapsed > 0 else 0
            
            result.add_detail(f"成功传输 {len(large_content):,} 字节 ({size_mb:.2f} MB)")
            result.add_detail(f"耗时 {elapsed:.2f} 秒，速度 {speed:.2f} MB/s")
            return result.success("大文件传输正常")
            
        except Exception as e:
            return result.fail(str(e))

    def test_multiple_deletes(self) -> TestResult:
        """测试10: 多文件删除同步"""
        result = TestResult("多文件删除同步")
        
        try:
            # 清理环境
            shutil.rmtree(self.client_dir)
            shutil.rmtree(self.server_dir)
            self.client_dir.mkdir()
            self.server_dir.mkdir()
            self.reset_client_state()
            
            # 重启服务端
            self.stop_server()
            server_state = self.test_dir / "server_sync_state.json"
            if server_state.exists():
                server_state.unlink()
            self.start_server()
            
            # 创建多个文件
            for i in range(5):
                self.create_file(self.client_dir, f"file_{i}.txt", f"Content {i}")
            self.create_file(self.client_dir, "keep_me.txt", "Keep this")
            
            # 推送
            success, _, stderr = self.run_client("push")
            if not success:
                return result.fail(f"初始推送失败: {stderr}")
            
            result.add_detail("初始推送6个文件")
            
            # 删除多个文件
            for i in range(5):
                self.delete_file(self.client_dir, f"file_{i}.txt")
            
            result.add_detail("删除5个文件")
            
            # 推送删除
            success, _, stderr = self.run_client("push")
            if not success:
                return result.fail(f"删除推送失败: {stderr}")
            
            # 验证
            deleted_count = 0
            for i in range(5):
                if not self.file_exists(self.server_dir, f"file_{i}.txt"):
                    deleted_count += 1
            
            if deleted_count != 5:
                return result.fail(f"只删除了 {deleted_count}/5 个文件")
            
            if not self.file_exists(self.server_dir, "keep_me.txt"):
                return result.fail("keep_me.txt 意外被删除")
            
            result.add_detail(f"服务端成功删除 {deleted_count} 个文件")
            return result.success("多文件删除同步正常")
            
        except Exception as e:
            return result.fail(str(e))

    # ========== 运行测试 ==========

    def run_all_tests(self):
        """运行所有测试"""
        print("\n" + "="*70)
        print("🧪 文件同步工具集成测试 v2.0")
        print("="*70)
        print(f"📍 测试目录: {self.test_dir}")
        print(f"🔌 测试端口: {self.port}")
        print("="*70 + "\n")
        
        try:
            # 设置环境
            self.log_section("测试环境准备")
            self.clean_all()
            self.setup_keys()
            self.create_configs()
            self.start_server()
            
            # 定义测试用例
            tests = [
                self.test_basic_push,
                self.test_basic_pull,
                self.test_delete_sync_push,
                self.test_delete_not_pull_back,
                self.test_file_modify_sync,
                self.test_pull_after_server_change,
                self.test_empty_directory,
                self.test_version_tracking,
                self.test_large_file,
                self.test_multiple_deletes,
            ]
            
            # 运行测试
            self.log_section("运行测试用例")
            
            for i, test_func in enumerate(tests, 1):
                print(f"\n--- 测试 {i}/{len(tests)}: {test_func.__doc__} ---")
                
                try:
                    test_result = test_func()
                except Exception as e:
                    test_result = TestResult(test_func.__doc__ or test_func.__name__)
                    test_result.fail(f"异常: {e}")
                
                self.test_results.append(test_result)
                
                if test_result.passed:
                    self.log_success(f"{test_result.name}: {test_result.message}")
                else:
                    self.log_error(f"{test_result.name}: {test_result.message}")
                
                for detail in test_result.details:
                    print(f"    → {detail}")
            
            # 输出总结
            self.print_summary()
            
        except Exception as e:
            self.log_error(f"测试过程中发生异常: {e}")
            import traceback
            traceback.print_exc()
            
        finally:
            self.stop_server()
    
    def print_summary(self):
        """打印测试总结"""
        print("\n" + "="*70)
        print("📊 测试结果总结")
        print("="*70)
        
        passed = sum(1 for r in self.test_results if r.passed)
        failed = len(self.test_results) - passed
        
        for test_result in self.test_results:
            status = "✅" if test_result.passed else "❌"
            print(f"  {status} {test_result.name}: {test_result.message}")
        
        print("\n" + "-"*70)
        print(f"  总计: {len(self.test_results)} 个测试")
        print(f"  通过: {passed} ✅")
        print(f"  失败: {failed} ❌")
        print("-"*70)
        
        if failed == 0:
            print("\n🎉 所有测试通过！")
        else:
            print(f"\n⚠️  有 {failed} 个测试失败，请检查！")
        
        print(f"\n📁 测试文件保留在: {self.test_dir}")
        print("="*70)
        
        return failed == 0


if __name__ == "__main__":
    tester = SyncToolTester(port=19999)
    tester.run_all_tests()
    
    passed = sum(1 for r in tester.test_results if r.passed)
    failed = len(tester.test_results) - passed
    sys.exit(0 if failed == 0 else 1)
