# Fix thread detach issue

1. Run a long task in TUI, e.g., soothe -p "analyze this project arch"

2. Detach the thread via Ctrl+d

3. Make sure the thread is still running

4. Run soothe thread continue to attach

5. Make sure the history of running thread restored and new events updated
