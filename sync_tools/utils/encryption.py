#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
加密模块
提供AES加密和解密功能
"""

import os
import base64
from pathlib import Path
from typing import Tuple, Optional

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    print("警告: cryptography库未安装，加密功能不可用")
    print("安装命令: pip install cryptography")


class EncryptionManager:
    """加密管理类"""
    
    def __init__(self, key_file: Optional[str] = None, password: Optional[str] = None):
        """
        初始化加密管理器
        
        Args:
            key_file: 密钥文件路径
            password: 密码（用于生成密钥）
        """
        if not CRYPTO_AVAILABLE:
            raise ImportError("cryptography库未安装，无法使用加密功能")
        
        self.key_file = key_file
        self.key = None
        
        if key_file and Path(key_file).exists():
            self.key = self._load_key(key_file)
        elif password:
            self.key = self._derive_key_from_password(password)
        else:
            # 生成新密钥
            self.key = self._generate_key()
            if key_file:
                self._save_key(key_file, self.key)
    
    def _generate_key(self) -> bytes:
        """
        生成新的加密密钥
        
        Returns:
            32字节的密钥
        """
        return os.urandom(32)
    
    def _derive_key_from_password(self, password: str, salt: Optional[bytes] = None) -> bytes:
        """
        从密码派生密钥
        
        Args:
            password: 密码字符串
            salt: 盐值，如果为None则生成新的
            
        Returns:
            派生的密钥
        """
        if salt is None:
            salt = os.urandom(16)
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        
        key = kdf.derive(password.encode('utf-8'))
        return salt + key  # 将盐值附加到密钥前面
    
    def _load_key(self, key_file: str) -> bytes:
        """
        从文件加载密钥
        
        Args:
            key_file: 密钥文件路径
            
        Returns:
            密钥数据
        """
        try:
            with open(key_file, 'rb') as f:
                key_data = f.read()
            
            # 检查是否是base64编码
            try:
                return base64.b64decode(key_data)
            except:
                return key_data
                
        except (IOError, OSError) as e:
            print(f"加载密钥文件失败: {e}")
            raise
    
    def _save_key(self, key_file: str, key: bytes) -> bool:
        """
        保存密钥到文件
        
        Args:
            key_file: 密钥文件路径
            key: 密钥数据
            
        Returns:
            保存是否成功
        """
        try:
            # 确保目录存在
            Path(key_file).parent.mkdir(parents=True, exist_ok=True)
            
            # 使用base64编码保存
            with open(key_file, 'wb') as f:
                f.write(base64.b64encode(key))
            
            # 设置文件权限（仅所有者可读写）
            os.chmod(key_file, 0o600)
            print(f"密钥已保存到: {key_file}")
            return True
            
        except (IOError, OSError) as e:
            print(f"保存密钥文件失败: {e}")
            return False
    
    def encrypt_data(self, data: bytes) -> bytes:
        """
        加密数据
        
        Args:
            data: 要加密的数据
            
        Returns:
            加密后的数据
        """
        if not self.key:
            raise ValueError("未设置加密密钥")
        
        # 使用Fernet对称加密（更简单可靠）
        try:
            # 如果密钥包含盐值，提取实际密钥
            actual_key = self.key[-32:] if len(self.key) > 32 else self.key
            
            # Fernet需要32字节的base64编码密钥
            fernet_key = base64.urlsafe_b64encode(actual_key)
            fernet = Fernet(fernet_key)
            
            encrypted_data = fernet.encrypt(data)
            return encrypted_data
            
        except Exception as e:
            print(f"[DEBUG] 加密失败: {e}")
            raise
    
    def decrypt_data(self, encrypted_data: bytes) -> bytes:
        """
        解密数据
        
        Args:
            encrypted_data: 加密的数据
            
        Returns:
            解密后的数据
        """
        if not self.key:
            raise ValueError("未设置加密密钥")
        
        try:
            # 如果密钥包含盐值，提取实际密钥
            actual_key = self.key[-32:] if len(self.key) > 32 else self.key
            
            # Fernet需要32字节的base64编码密钥
            fernet_key = base64.urlsafe_b64encode(actual_key)
            fernet = Fernet(fernet_key)
            
            decrypted_data = fernet.decrypt(encrypted_data)
            return decrypted_data
            
        except Exception as e:
            raise
    
    def encrypt_file(self, input_file: str, output_file: str) -> bool:
        """
        加密文件
        
        Args:
            input_file: 输入文件路径
            output_file: 输出文件路径
            
        Returns:
            加密是否成功
        """
        try:
            with open(input_file, 'rb') as f_in:
                data = f_in.read()
            
            encrypted_data = self.encrypt_data(data)
            
            with open(output_file, 'wb') as f_out:
                f_out.write(encrypted_data)
            
            print(f"文件加密成功: {input_file} -> {output_file}")
            return True
            
        except Exception as e:
            print(f"文件加密失败: {e}")
            return False
    
    def decrypt_file(self, input_file: str, output_file: str) -> bool:
        """
        解密文件
        
        Args:
            input_file: 输入文件路径
            output_file: 输出文件路径
            
        Returns:
            解密是否成功
        """
        try:
            with open(input_file, 'rb') as f_in:
                encrypted_data = f_in.read()
            
            data = self.decrypt_data(encrypted_data)
            
            with open(output_file, 'wb') as f_out:
                f_out.write(data)
            
            print(f"文件解密成功: {input_file} -> {output_file}")
            return True
            
        except Exception as e:
            print(f"文件解密失败: {e}")
            return False
    
    def get_key_info(self) -> dict:
        """
        获取密钥信息
        
        Returns:
            密钥信息字典
        """
        if not self.key:
            return {"status": "no_key"}
        
        return {
            "status": "loaded",
            "key_length": len(self.key),
            "has_salt": len(self.key) > 32,
            "key_file": self.key_file
        }


def generate_key_pair(server_key_file: str = "server.key", 
                     client_key_file: str = "client.key",
                     password: Optional[str] = None) -> bool:
    """
    生成服务端和客户端密钥对
    
    Args:
        server_key_file: 服务端密钥文件
        client_key_file: 客户端密钥文件  
        password: 密码（可选）
        
    Returns:
        生成是否成功
    """
    if not CRYPTO_AVAILABLE:
        print("错误: cryptography库未安装")
        return False
    
    try:
        print("生成密钥对...")
        
        # 为服务端和客户端生成相同的密钥（用于对称加密）
        if password:
            key = EncryptionManager(password=password).key
        else:
            key = os.urandom(32)
        
        # 保存服务端密钥
        server_manager = EncryptionManager()
        server_manager.key = key
        if key is None:
            print("错误: 密钥生成失败，无法保存密钥文件")
            return False
        server_manager._save_key(server_key_file, key)
        
        # 保存客户端密钥
        client_manager = EncryptionManager()
        client_manager.key = key
        client_manager._save_key(client_key_file, key)
        
        print(f"密钥对生成成功:")
        print(f"  服务端密钥: {server_key_file}")
        print(f"  客户端密钥: {client_key_file}")
        return True
        
    except Exception as e:
        print(f"生成密钥对失败: {e}")
        return False


def main():
    """命令行工具入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='加密工具')
    parser.add_argument('--generate-keys', action='store_true', help='生成密钥对')
    parser.add_argument('--server-key', default='server.key', help='服务端密钥文件')
    parser.add_argument('--client-key', default='client.key', help='客户端密钥文件')
    parser.add_argument('--password', help='密码（用于派生密钥）')
    parser.add_argument('--encrypt', help='加密文件')
    parser.add_argument('--decrypt', help='解密文件')
    parser.add_argument('--key-file', help='密钥文件')
    parser.add_argument('--output', help='输出文件')
    
    args = parser.parse_args()
    
    if args.generate_keys:
        generate_key_pair(args.server_key, args.client_key, args.password)
    elif args.encrypt:
        if not args.key_file or not args.output:
            print("加密需要指定 --key-file 和 --output")
        else:
            manager = EncryptionManager(args.key_file)
            manager.encrypt_file(args.encrypt, args.output)
    elif args.decrypt:
        if not args.key_file or not args.output:
            print("解密需要指定 --key-file 和 --output")
        else:
            manager = EncryptionManager(args.key_file)
            manager.decrypt_file(args.decrypt, args.output)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
