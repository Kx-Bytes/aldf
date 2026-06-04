import sys, os, traceback
sys.path.append(os.path.abspath('./backend'))
from app.services.daily_sync import process_daily_sync

try:
    process_daily_sync()
    print('Daily sync completed successfully')
except Exception as e:
    print('Error during daily sync:', e)
    traceback.print_exc()
