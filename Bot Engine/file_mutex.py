import os
import time
import logging

logger = logging.getLogger(__name__)

class FileMutex:
    """A simple file-based mutex to synchronize access across multiple processes."""
    
    def __init__(self, lock_file: str, timeout: float = 30.0):
        self.lock_file = lock_file
        self.timeout = timeout

    def acquire(self) -> bool:
        """Attempt to acquire the lock. Blocks until acquired or timeout."""
        start_time = time.time()
        while True:
            try:
                # O_CREAT | O_EXCL ensures atomic creation. Fails if file exists.
                fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(fd, b"locked")
                os.close(fd)
                return True
            except OSError as e:
                # e.errno == 17 is FileExistsError
                # e.errno == 13 is PermissionError
                # e.errno == 32 is Sharing Violation (Windows)
                
                if time.time() - start_time > self.timeout:
                    # To prevent deadlocks if a process crashes while holding lock
                    try:
                        file_age = time.time() - os.path.getmtime(self.lock_file)
                        if file_age > self.timeout:
                            logger.warning(f"Lock {self.lock_file} seems stale (age {file_age:.1f}s). Breaking it.")
                            try:
                                os.remove(self.lock_file)
                                continue # Try acquiring again
                            except OSError:
                                pass
                    except OSError:
                        pass
                    return False
                time.sleep(0.1) # Wait and retry
            except Exception as e:
                logger.error(f"Error acquiring lock {self.lock_file}: {e}")
                time.sleep(0.1)
                if time.time() - start_time > self.timeout:
                    return False

    def release(self):
        """Release the lock."""
        try:
            if os.path.exists(self.lock_file):
                os.remove(self.lock_file)
        except OSError as e:
            logger.error(f"Error releasing lock {self.lock_file}: {e}")

class MT5Lock(FileMutex):
    """Specific lock for MT5 Terminal access."""
    def __init__(self):
        super().__init__("mt5_terminal.lock", timeout=60.0)

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError("Failed to acquire MT5 lock within timeout.")
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

class MemoryLock(FileMutex):
    """Specific lock for trade_memory.json access."""
    def __init__(self):
        super().__init__("trade_memory.lock", timeout=10.0)
        
    def __enter__(self):
        if not self.acquire():
            raise TimeoutError("Failed to acquire Memory lock within timeout.")
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
