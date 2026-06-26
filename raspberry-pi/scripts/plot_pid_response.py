"""
Plot PID Step Response from CSV Data
Generate publication-quality graphs for thesis report

Usage:
    python plot_pid_response.py logs/pid/pid_step_response_30rpm_20260413_103000.csv

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import pandas as pd
import matplotlib.pyplot as plt
import sys
from pathlib import Path

def plot_pid_response(csv_file, output_file=None):
    """
    Plot RPM vs Time from PID logger CSV file
    
    Args:
        csv_file: Path to CSV file
        output_file: Output PNG file (optional, auto-generated if None)
    """
    # Read CSV
    df = pd.read_csv(csv_file)
    
    # Extract data
    time = df['elapsed_time']
    setpoint = df['setpoint']
    rpm_actual = df['rpm_actual']
    
    # Get test info from filename
    filename = Path(csv_file).stem
    parts = filename.split('_')
    
    # Extract setpoint value
    setpoint_value = setpoint.iloc[0]
    
    # Create figure
    plt.figure(figsize=(10, 6))
    
    # Plot setpoint (dashed line)
    plt.plot(time, setpoint, 'b--', linewidth=2, label=f'Setpoint ({setpoint_value} RPM)')
    
    # Plot actual RPM (solid line)
    plt.plot(time, rpm_actual, 'g-', linewidth=2, label='RPM Aktual')
    
    # Add grid
    plt.grid(True, alpha=0.3, linestyle='--')
    
    # Labels and title
    plt.xlabel('Waktu (detik)', fontsize=12, fontweight='bold')
    plt.ylabel('RPM (Rotasi Per Menit)', fontsize=12, fontweight='bold')
    plt.title(f'Respons Step Kendali PID pada Setpoint {setpoint_value} RPM', 
              fontsize=14, fontweight='bold', pad=20)
    
    # Legend
    plt.legend(loc='best', fontsize=11, framealpha=0.9)
    
    # Tight layout
    plt.tight_layout()
    
    # Save figure
    if output_file is None:
        output_file = csv_file.replace('.csv', '.png')
    
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✓ Grafik disimpan: {output_file}")
    
    # Show plot
    plt.show()
    
    # Calculate and print parameters
    print("\n" + "="*60)
    print("PARAMETER RESPONS TRANSIEN")
    print("="*60)
    
    # Rise time (10% to 90%)
    threshold_10 = setpoint_value * 0.1
    threshold_90 = setpoint_value * 0.9
    
    time_10 = None
    time_90 = None
    
    for i, rpm in enumerate(rpm_actual):
        if time_10 is None and rpm >= threshold_10:
            time_10 = time.iloc[i]
        if time_90 is None and rpm >= threshold_90:
            time_90 = time.iloc[i]
            break
    
    if time_10 and time_90:
        rise_time = time_90 - time_10
        print(f"Rise Time (tr):           {rise_time:.3f} detik")
    
    # Overshoot
    max_rpm = rpm_actual.max()
    overshoot = ((max_rpm - setpoint_value) / setpoint_value * 100) if setpoint_value > 0 else 0
    print(f"Overshoot:                {overshoot:.2f}%")
    
    # Settling time (within ±2% of setpoint)
    threshold_upper = setpoint_value * 1.02
    threshold_lower = setpoint_value * 0.98
    
    settling_time = None
    for i in range(len(rpm_actual) - 1, -1, -1):
        if rpm_actual.iloc[i] < threshold_lower or rpm_actual.iloc[i] > threshold_upper:
            settling_time = time.iloc[i]
            break
    
    if settling_time:
        print(f"Settling Time (ts):       {settling_time:.3f} detik")
    
    # Steady-state error
    steady_start = int(len(rpm_actual) * 0.8)
    steady_rpm = rpm_actual.iloc[steady_start:].mean()
    sse = setpoint_value - steady_rpm
    print(f"Steady-State Error (ess): {sse:.2f} RPM")
    
    print("="*60)
    print(f"\nTotal data points: {len(rpm_actual)}")
    print(f"Duration: {time.iloc[-1]:.2f} detik")
    print(f"Mean RPM: {rpm_actual.mean():.2f} RPM")
    print(f"Std Dev: {rpm_actual.std():.2f} RPM")
    print(f"Min RPM: {rpm_actual.min():.2f} RPM")
    print(f"Max RPM: {rpm_actual.max():.2f} RPM")
    print("="*60)

def main():
    if len(sys.argv) < 2:
        print("Usage: python plot_pid_response.py <csv_file> [output_file]")
        print("\nExample:")
        print("  python plot_pid_response.py logs/pid/pid_step_response_30rpm_20260413_103000.csv")
        print("  python plot_pid_response.py logs/pid/pid_step_response_30rpm_20260413_103000.csv output.png")
        sys.exit(1)
    
    csv_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not Path(csv_file).exists():
        print(f"Error: File tidak ditemukan: {csv_file}")
        sys.exit(1)
    
    plot_pid_response(csv_file, output_file)

if __name__ == "__main__":
    main()
