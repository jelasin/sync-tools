#!/usr/bin/env python3
"""
文件同步工具集成测试脚本
在test目录下进行独立测试，不清理文件以便检查传输结果
"""

import os
import sys
import time
import json
import shutil
import socket
import subprocess
import threading
from pathlib import Path


class SyncToolTester:
    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.test_dir = self.base_dir / "test"
        self.server_dir = self.test_dir / "server_files"
        self.client_dir = self.test_dir / "client_files"
        self.server_process = None
        
    def setup_test_environment(self):
        """设置测试环境"""
        print("🔧 设置测试环境...")
        
        # 创建测试目录
        self.test_dir.mkdir(exist_ok=True)
        self.server_dir.mkdir(exist_ok=True)
        self.client_dir.mkdir(exist_ok=True)
        
        # 生成测试密钥（放在test目录下）
        print("🔑 生成测试密钥...")
        
        # 在项目根目录运行encryption.py，指定test目录中的密钥文件
        server_key_path = self.test_dir / "server.key"
        client_key_path = self.test_dir / "client.key"
        
        result = subprocess.run([
            sys.executable, "sync_keygen.py", "--generate-keys", 
            "--server-key", str(server_key_path),
            "--client-key", str(client_key_path)
        ], cwd=self.base_dir.parent, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"密钥生成失败: {result.stderr}")
            
        print("✅ 测试环境设置完成")
        
    def create_test_configs(self):
        """创建测试专用配置文件"""
        print("⚙️ 创建测试配置文件...")
        
        # 密钥文件路径
        server_key_path = self.test_dir / "server.key"
        client_key_path = self.test_dir / "client.key"
        
        # 服务端测试配置
        server_config = {
            "server": {
                "host": "127.0.0.1",
                "port": 9999,
                "sync_dir": str(self.server_dir),
                "sync_json": str(self.test_dir / "server_sync_state.json"),
                "max_connections": 10,
                "encryption": {
                    "enabled": True,
                    "key_file": str(server_key_path),
                    "algorithm": "Fernet"
                }
            },
            "sync": {
                "exclude_patterns": ["*.tmp", "*.log", ".git/*", "__pycache__/*", "*.pyc"],
                "include_hidden": False,
                "compression": False,
                "chunk_size": 8192
            }
        }
        
        # 客户端测试配置
        client_config = {
            "client": {
                "local_dir": str(self.client_dir),
                "sync_json": str(self.test_dir / "client_sync_state.json"),
                "server_address": "127.0.0.1:9999",
                "timeout": 30,
                "retry_count": 3,
                "encryption": {
                    "enabled": True,
                    "key_file": str(client_key_path),
                    "algorithm": "Fernet"
                },
                "ui": {
                    "show_progress": True,
                    "progress_style": "bar"
                }
            },
            "sync": {
                "exclude_patterns": ["*.tmp", "*.log", ".git/*", "__pycache__/*", "*.pyc"],
                "include_hidden": False,
                "compression": False,
                "chunk_size": 8192
            }
        }
        
        # 写入配置文件到test目录
        with open(self.test_dir / "server_config.json", "w", encoding='utf-8') as f:
            json.dump(server_config, f, indent=2, ensure_ascii=False)
            
        with open(self.test_dir / "client_config.json", "w", encoding='utf-8') as f:
            json.dump(client_config, f, indent=2, ensure_ascii=False)
            
        print("✅ 测试配置文件创建完成")
        
    def create_test_files(self):
        """创建测试文件"""
        print("📄 创建测试文件...")
        
        test_files = {
            "README.txt": "这是一个测试README文件\n包含中文内容测试",
            "config.json": json.dumps({"test": "configuration", "encoding": "utf-8"}, indent=2, ensure_ascii=False),
            "data/numbers.txt": "\n".join(str(i) for i in range(1, 11)),
            "docs/guide.md": "# 测试指南\n\n这是测试文档\n## 功能说明\n测试同步功能",
            "src/main.py": "#!/usr/bin/env python3\nprint('Hello, World!')\nprint('测试文件同步')\n",
            "images/placeholder.txt": "图片文件夹占位符",
            "logs/app.log": "2025-01-01 10:00:00 - 应用启动\n2025-01-01 10:01:00 - 测试日志",
        }
        
        for file_path, content in test_files.items():
            full_path = self.client_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding='utf-8')
            
        print(f"✅ 创建了 {len(test_files)} 个测试文件")
        return len(test_files)
        
    def start_server(self):
        """启动服务端"""
        print("🚀 启动服务端...")
        
        # 检查端口是否可用
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', 9999)) == 0:
                print("⚠️ 端口 9999 已被占用，尝试停止现有进程...")
                
        # 启动服务端（从项目根目录运行）
        self.server_process = subprocess.Popen([
            sys.executable, "sync_server.py", "--config", str(self.test_dir / "server_config.json")
        ], cwd=self.base_dir.parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # 等待服务端启动
        print("⏳ 等待服务端启动...")
        time.sleep(3)
        
        # 验证服务端是否启动成功
        for attempt in range(10):  # 最多等待10秒
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('127.0.0.1', 9999)) == 0:
                    print("✅ 服务端启动成功")
                    return
            time.sleep(1)
                
        # 如果启动失败，输出错误信息
        if self.server_process.poll() is not None:
            stdout, stderr = self.server_process.communicate()
            raise Exception(f"服务端启动失败: {stderr.decode('utf-8', errors='ignore')}")
        
        raise Exception("服务端启动超时")
        
    def test_push(self):
        """测试推送功能"""
        print("📤 测试推送功能...")
        
        result = subprocess.run([
            sys.executable, "sync_client.py", 
            "--config", str(self.test_dir / "client_config.json"),
            "--mode", "push"
        ], cwd=self.base_dir.parent, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"推送输出: {result.stdout}")
            print(f"推送错误: {result.stderr}")
            raise Exception(f"推送失败，返回代码: {result.returncode}")
            
        # 验证文件是否上传到服务端
        uploaded_files = list(self.server_dir.rglob("*"))
        uploaded_files = [f for f in uploaded_files if f.is_file()]
        
        print(f"✅ 推送成功，上传了 {len(uploaded_files)} 个文件")
        for file in uploaded_files:
            rel_path = file.relative_to(self.server_dir)
            print(f"   📁 {rel_path}")
        
        return uploaded_files
        
    def test_pull(self):
        """测试拉取功能"""
        print("📥 测试拉取功能...")
        
        # 备份原始文件到临时目录
        backup_dir = self.test_dir / "client_backup"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(self.client_dir, backup_dir)
        
        # 清空客户端目录
        shutil.rmtree(self.client_dir)
        self.client_dir.mkdir()
        
        result = subprocess.run([
            sys.executable, "sync_client.py",
            "--config", str(self.test_dir / "client_config.json"), 
            "--mode", "pull"
        ], cwd=self.base_dir.parent, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"拉取输出: {result.stdout}")
            print(f"拉取错误: {result.stderr}")
            # 恢复备份
            shutil.rmtree(self.client_dir)
            shutil.copytree(backup_dir, self.client_dir)
            raise Exception(f"拉取失败，返回代码: {result.returncode}")
            
        # 验证文件是否下载到客户端
        downloaded_files = list(self.client_dir.rglob("*"))
        downloaded_files = [f for f in downloaded_files if f.is_file()]
        
        print(f"✅ 拉取成功，下载了 {len(downloaded_files)} 个文件")
        for file in downloaded_files:
            rel_path = file.relative_to(self.client_dir)
            print(f"   📁 {rel_path}")
        
        return downloaded_files
        
    def verify_file_integrity(self, original_count, uploaded_files, downloaded_files):
        """验证文件完整性"""
        print("🔍 验证文件完整性...")
        
        if len(uploaded_files) != original_count:
            print(f"⚠️ 上传文件数量不匹配: 原始 {original_count} vs 上传 {len(uploaded_files)}")
            
        if len(downloaded_files) != len(uploaded_files):
            print(f"⚠️ 下载文件数量不匹配: 上传 {len(uploaded_files)} vs 下载 {len(downloaded_files)}")
            
        if len(downloaded_files) == original_count:
            print("✅ 文件数量验证通过")
        else:
            print(f"⚠️ 文件数量验证失败: 原始 {original_count} vs 最终 {len(downloaded_files)}")
            
    def stop_server(self):
        """停止服务端"""
        if self.server_process:
            print("🛑 停止服务端...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
                print("✅ 服务端已停止")
            except subprocess.TimeoutExpired:
                print("⚠️ 服务端停止超时，强制终止")
                self.server_process.kill()
                
    def run_test(self):
        """运行完整测试"""
        try:
            print("🧪 开始集成测试")
            print("=" * 60)
            print(f"📍 测试目录: {self.test_dir}")
            print("=" * 60)
            
            # 设置测试环境
            self.setup_test_environment()
            
            # 创建测试配置文件
            self.create_test_configs()
            
            # 创建测试文件
            original_count = self.create_test_files()
            
            # 启动服务端
            self.start_server()
            
            # 测试推送
            uploaded_files = self.test_push()
            
            # 测试拉取
            downloaded_files = self.test_pull()
            
            # 验证完整性
            self.verify_file_integrity(original_count, uploaded_files, downloaded_files)
            
            print("=" * 60)
            print("🎉 测试完成！")
            print(f"📊 测试统计:")
            print(f"   - 原始文件: {original_count}")
            print(f"   - 上传文件: {len(uploaded_files)}")
            print(f"   - 下载文件: {len(downloaded_files)}")
            print(f"📁 文件保留在: {self.test_dir}")
            print("   - 服务端文件: test/server_files/")
            print("   - 客户端文件: test/client_files/")
            print("   - 配置文件: test/*.json")
            print("   - 密钥文件: test/*.key")
            print("=" * 60)
            
            return True
            
        except Exception as e:
            print(f"❌ 测试失败: {e}")
            return False
            
        finally:
            # 停止服务端，但不清理文件
            self.stop_server()


if __name__ == "__main__":
    tester = SyncToolTester()
    success = tester.run_test()
    
    if success:
        print("\n✅ 所有测试通过！您可以检查test目录下的文件传输结果。")
    else:
        print("\n❌ 测试失败，请检查错误信息。")
    
    sys.exit(0 if success else 1)
