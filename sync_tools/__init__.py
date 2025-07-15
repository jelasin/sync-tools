"""
文件同步工具包
"""

__version__ = "1.0.0"
__author__ = "Sync Tools Team"
__description__ = "A secure file synchronization tool with encryption support"

from sync_tools.core.sync_core import SyncCore
from sync_tools.core.server import SyncServer
from sync_tools.core.client import SyncClient

__all__ = ['SyncCore', 'SyncServer', 'SyncClient']
