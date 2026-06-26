"""
Batch Plot All PID Step Responses
Generate all graphs from PID logger CSV files

Usage:
    python plot_all_pid_responses.py

This will find all CSV files in logs/pid/ and generate PNG graphs

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import os

def plot_pid_response(csv_file, output_dir="analysis_output/pid/graphs"):
    """Plot single PID response"""
    # Create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Read CSV
    df = pd.read_csv(csv_file)
    
    # Extract data
    time = df['elapsed_time']
    setpoint = df['setpoint']
    rpm_actual = df['rpm_actual']
    
    # Get setpoint value
    setpoint_value = setpoint.iloc[0]
    
    # Get test name from filename
    filename = Path(csv_file).stem
    
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
    output_file = Path(output_dir) / f"{filename}.png"
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.close()
    
    return output_file

def main():
    # Find all CSV files in logs/pid/
    csv_dir = Path("logs/pid")
    
    if not csv_dir.exists():
        print(f"Error: Directory tidak ditemukan: {csv_dir}")
        print("Pastikan Anda sudah menjalankan PID Logger dan menghasilkan data CSV")
        return
    
    csv_files = list(csv_dir.glob("pid_*.csv"))
    
    if not csv_files:
        print(f"Tidak ada file CSV ditemukan di {csv_dir}")
        print("Jalankan PID Logger terlebih dahulu untuk menghasilkan data")
        return
    
    print("="*70)
    print("BATCH PLOT PID STEP RESPONSES")
    print("="*70)
    print(f"Ditemukan {len(csv_files)} file CSV\n")
    
    output_files = []
    
    for i, csv_file in enumerate(csv_files, 1):
        print(f"[{i}/{len(csv_files)}] Processing: {csv_file.name}")
        
        try:
            output_file = plot_pid_response(csv_file)
            output_files.append(output_file)
            print(f"  ✓ Grafik disimpan: {output_file}")
        except Exception as e:
            print(f"  ✗ Error: {e}")
    
    print("\n" + "="*70)
    print(f"SELESAI - {len(output_files)} grafik berhasil dibuat")
    print("="*70)
    print(f"\nLokasi output: analysis_output/pid/graphs/")
    print("\nFile yang dibuat:")
    for f in output_files:
        print(f"  - {f.name}")
    
    print("\n💡 Tips:")
    print("  1. Buka file PNG untuk melihat grafik")
    print("  2. Copy grafik ke folder 'Laporan PA/gambar/bab_4/'")
    print("  3. Insert ke LaTeX dengan \\includegraphics")

if __name__ == "__main__":
    main()
