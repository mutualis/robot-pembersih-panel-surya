"""
PID Control Data Logger
Logs RPM data for PID analysis and Bab 4 report

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import time
import json
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import statistics


class PIDLogger:
    """Log and analyze PID control performance"""
    
    def __init__(self, log_dir: str = "logs/pid", buffer_size: int = 1000):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.buffer_size = buffer_size
        self.data_buffer = []
        
        # Session info
        self.session_id = None
        self.session_file = None
        self.csv_file = None
        
        # Test parameters
        self.setpoint = 0
        self.test_name = ""
        self.start_time = None
        self.is_logging = False
        
        print(f"[PIDLogger] Initialized. Logs: {self.log_dir}")
    
    def start_logging(self, setpoint: float, test_name: str = "step_response"):
        """Start a new logging session"""
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.setpoint = setpoint
        self.test_name = test_name
        self.start_time = time.time()
        self.is_logging = True
        self.data_buffer = []
        
        # Create files
        self.session_file = self.log_dir / f"pid_{test_name}_{int(setpoint)}rpm_{self.session_id}.json"
        self.csv_file = self.log_dir / f"pid_{test_name}_{int(setpoint)}rpm_{self.session_id}.csv"
        
        # Initialize CSV
        with open(self.csv_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'elapsed_time', 'setpoint', 'rpm_actual', 'error', 'pwm'])
        
        print(f"[PIDLogger] Started logging: {test_name} @ {setpoint} RPM")
        print(f"[PIDLogger] Session: {self.session_id}")
    
    def log_data_point(self, rpm_actual: float, pwm: int = 0):
        """Log a single data point"""
        if not self.is_logging:
            return
        
        elapsed = time.time() - self.start_time
        error = self.setpoint - rpm_actual
        
        data_point = {
            'timestamp': datetime.now().isoformat(),
            'elapsed_time': round(elapsed, 3),
            'setpoint': self.setpoint,
            'rpm_actual': round(rpm_actual, 2),
            'error': round(error, 2),
            'pwm': pwm
        }
        
        # Add to buffer
        self.data_buffer.append(data_point)
        
        # Write to CSV (with error handling to prevent data loss)
        try:
            with open(self.csv_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    data_point['timestamp'],
                    data_point['elapsed_time'],
                    data_point['setpoint'],
                    data_point['rpm_actual'],
                    data_point['error'],
                    data_point['pwm']
                ])
        except (IOError, OSError) as e:
            print(f"[PIDLogger] CSV write error: {e}")
    
    def stop_logging(self):
        """Stop logging and generate report"""
        if not self.is_logging:
            return None
        
        self.is_logging = False
        
        # Generate analysis
        report = self.analyze_step_response()
        
        # Save to JSON
        with open(self.session_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n[PIDLogger] Logging stopped")
        print(f"[PIDLogger] Data points: {len(self.data_buffer)}")
        print(f"[PIDLogger] Files saved:")
        print(f"  CSV:  {self.csv_file}")
        print(f"  JSON: {self.session_file}")
        
        return report
    
    def analyze_step_response(self) -> Dict:
        """Analyze step response characteristics"""
        if len(self.data_buffer) < 10:
            return {'error': 'Insufficient data points'}
        
        # Extract data
        times = [d['elapsed_time'] for d in self.data_buffer]
        rpms = [d['rpm_actual'] for d in self.data_buffer]
        errors = [d['error'] for d in self.data_buffer]
        
        # Calculate parameters
        setpoint = self.setpoint
        
        # 1. Rise Time (10% to 90% of setpoint)
        rise_time = self._calculate_rise_time(times, rpms, setpoint)
        
        # 2. Overshoot
        max_rpm = max(rpms)
        overshoot_percent = ((max_rpm - setpoint) / setpoint * 100) if setpoint > 0 else 0
        
        # 3. Settling Time (within ±2% of setpoint)
        settling_time = self._calculate_settling_time(times, rpms, setpoint, tolerance=0.02)
        
        # 4. Steady-State Error (average of last 20% of data)
        steady_start = int(len(rpms) * 0.8)
        steady_rpms = rpms[steady_start:]
        steady_state_rpm = statistics.mean(steady_rpms) if steady_rpms else 0
        steady_state_error = setpoint - steady_state_rpm
        
        # 5. Statistics
        mean_rpm = statistics.mean(rpms)
        std_rpm = statistics.stdev(rpms) if len(rpms) > 1 else 0
        min_rpm = min(rpms)
        max_rpm = max(rpms)
        
        report = {
            'session_id': self.session_id,
            'test_name': self.test_name,
            'setpoint': setpoint,
            'data_points': len(self.data_buffer),
            'duration_sec': round(times[-1], 2),
            
            'transient_response': {
                'rise_time_sec': round(rise_time, 3) if rise_time else None,
                'overshoot_percent': round(overshoot_percent, 2),
                'settling_time_sec': round(settling_time, 3) if settling_time else None,
                'steady_state_error_rpm': round(steady_state_error, 2)
            },
            
            'statistics': {
                'mean_rpm': round(mean_rpm, 2),
                'std_rpm': round(std_rpm, 2),
                'min_rpm': round(min_rpm, 2),
                'max_rpm': round(max_rpm, 2)
            },
            
            'files': {
                'csv': str(self.csv_file),
                'json': str(self.session_file)
            }
        }
        
        return report
    
    def _calculate_rise_time(self, times: List[float], rpms: List[float], setpoint: float) -> Optional[float]:
        """Calculate rise time (10% to 90% of setpoint)"""
        threshold_10 = setpoint * 0.1
        threshold_90 = setpoint * 0.9
        
        time_10 = None
        time_90 = None
        
        for i, rpm in enumerate(rpms):
            if time_10 is None and rpm >= threshold_10:
                time_10 = times[i]
            if time_90 is None and rpm >= threshold_90:
                time_90 = times[i]
                break
        
        if time_10 is not None and time_90 is not None:
            return time_90 - time_10
        return None
    
    def _calculate_settling_time(self, times: List[float], rpms: List[float], 
                                  setpoint: float, tolerance: float = 0.02) -> Optional[float]:
        """Calculate settling time (time to stay within ±tolerance of setpoint)"""
        threshold_upper = setpoint * (1 + tolerance)
        threshold_lower = setpoint * (1 - tolerance)
        
        # Find last time RPM was outside tolerance band
        last_outside = None
        for i in range(len(rpms) - 1, -1, -1):
            if rpms[i] < threshold_lower or rpms[i] > threshold_upper:
                last_outside = times[i]
                break
        
        if last_outside is not None:
            return last_outside
        
        # If never settled, return total time
        return times[-1] if times else None
    
    def export_for_report(self, output_dir: str = "analysis_output/pid"):
        """Export formatted data for report"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        if not self.session_file or not self.session_file.exists():
            print("[PIDLogger] No session data to export")
            return None
        
        # Load report
        with open(self.session_file, 'r') as f:
            report = json.load(f)
        
        # Generate LaTeX-friendly text file
        latex_file = output_path / f"pid_report_{self.test_name}_{int(self.setpoint)}rpm_{self.session_id}.txt"
        
        with open(latex_file, 'w', encoding='utf-8') as f:
            f.write("=" * 70 + "\n")
            f.write("PID CONTROL STEP RESPONSE ANALYSIS\n")
            f.write(f"Test: {report['test_name']}\n")
            f.write(f"Setpoint: {report['setpoint']} RPM\n")
            f.write(f"Session: {report['session_id']}\n")
            f.write("=" * 70 + "\n\n")
            
            f.write("TRANSIENT RESPONSE PARAMETERS\n")
            f.write("-" * 70 + "\n")
            tr = report['transient_response']
            f.write(f"Rise Time (tr):           {tr['rise_time_sec']} seconds\n")
            f.write(f"Overshoot:                {tr['overshoot_percent']}%\n")
            f.write(f"Settling Time (ts):       {tr['settling_time_sec']} seconds\n")
            f.write(f"Steady-State Error (ess): {tr['steady_state_error_rpm']} RPM\n\n")
            
            f.write("STATISTICS\n")
            f.write("-" * 70 + "\n")
            stats = report['statistics']
            f.write(f"Mean RPM:     {stats['mean_rpm']} RPM\n")
            f.write(f"Std Dev:      {stats['std_rpm']} RPM\n")
            f.write(f"Min RPM:      {stats['min_rpm']} RPM\n")
            f.write(f"Max RPM:      {stats['max_rpm']} RPM\n\n")
            
            f.write("TEST INFO\n")
            f.write("-" * 70 + "\n")
            f.write(f"Data Points:  {report['data_points']}\n")
            f.write(f"Duration:     {report['duration_sec']} seconds\n\n")
            
            f.write("=" * 70 + "\n")
            f.write("DATA FILES\n")
            f.write(f"  CSV:  {report['files']['csv']}\n")
            f.write(f"  JSON: {report['files']['json']}\n")
            f.write("=" * 70 + "\n")
        
        print(f"\n[PIDLogger] Export Complete:")
        print(f"  LaTeX Report: {latex_file}")
        print(f"  CSV Data: {self.csv_file}")
        print(f"  JSON Report: {self.session_file}")
        
        return {
            'latex_file': str(latex_file),
            'csv_file': str(self.csv_file),
            'json_file': str(self.session_file)
        }
    
    def get_current_data(self) -> List[Dict]:
        """Get current buffer data for real-time display"""
        return self.data_buffer.copy()
    
    def get_status(self) -> Dict:
        """Get current logging status"""
        return {
            'is_logging': self.is_logging,
            'session_id': self.session_id,
            'test_name': self.test_name,
            'setpoint': self.setpoint,
            'data_points': len(self.data_buffer),
            'elapsed_time': round(time.time() - self.start_time, 2) if self.start_time else 0
        }
