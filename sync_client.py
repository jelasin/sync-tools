#!/usr/bin/env python3
"""
同步工具客户端入口
"""

import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from sync_tools.core.client import main

if __name__ == "__main__":
    main()
