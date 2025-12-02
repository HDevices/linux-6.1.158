#!/usr/bin/env python3
import os
import sys
import subprocess
import json
import shutil
import time

# --- CONFIGURACIÓN DE RUTAS ---
WORKSPACE = "/home/dev/gemini_workspace/Allwinner_A13_Tablet"
KERNEL_SRC = os.path.join(WORKSPACE, "Kernel/LTS/kernel_build/linux-6.1.158/arch/arm/boot/zImage")
DTB_SRC    = os.path.join(WORKSPACE, "Kernel/LTS/kernel_build/linux-6.1.158/arch/arm/boot/dts/sun5i-a13-inet-86ve-rev02.dtb")
UBOOT_MODERN_SRC = os.path.join(WORKSPACE, "U-Boot/u-boot/u-boot-sunxi-with-spl.bin")
UBOOT_LEGACY_SRC = os.path.join(WORKSPACE, "U-Boot/Legacy/u-boot-sunxi-with-spl.bin")

# Colores para la consola
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def check_root():
    if os.geteuid() != 0:
        print(f"{Colors.FAIL}Error: Este script necesita permisos de root para escribir en discos.{Colors.ENDC}")
        print(f"Por favor ejecuta: {Colors.BOLD}sudo python3 flash_tool.py{Colors.ENDC}")
        sys.exit(1)

def check_files():
    print(f"{Colors.HEADER}--- Verificando archivos compilados ---{Colors.ENDC}")
    for name, path in [("Kernel (zImage)", KERNEL_SRC), ("DTB", DTB_SRC), 
                       ("U-Boot Moderno", UBOOT_MODERN_SRC), ("U-Boot Legacy", UBOOT_LEGACY_SRC)]:
        if os.path.exists(path):
            print(f"{Colors.OKGREEN}[OK]{Colors.ENDC} {name} encontrado.")
        else:
            print(f"{Colors.FAIL}[FALTA]{Colors.ENDC} {name} no encontrado en: {path}")

def list_drives():
    try:
        # Listamos dispositivos, excluyendo loops y rams, buscando usb/sd
        cmd = ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,TRAN,MODEL,MOUNTPOINT,HOTPLUG"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        
        candidates = []
        for device in data.get("blockdevices", []):
            # Filtros para encontrar memorias USB/SD
            is_removable = device.get("hotplug") == True or device.get("tran") == "usb"
            is_disk = device.get("type") == "disk"
            
            if is_disk and is_removable:
                candidates.append(device)
        
        return candidates
    except Exception as e:
        print(f"{Colors.FAIL}Error al listar discos: {e}{Colors.ENDC}")
        return []

def select_drive(drives):
    print(f"\n{Colors.HEADER}--- Selecciona tu memoria ---{Colors.ENDC}")
    if not drives:
        print(f"{Colors.FAIL}No se detectaron memorias USB/SD externas.{Colors.ENDC}")
        sys.exit(1)

    for idx, drive in enumerate(drives):
        name = drive.get("name")
        size = drive.get("size")
        model = drive.get("model", "Desconocido")
        print(f"{Colors.BOLD}{idx + 1}. /dev/{name}{Colors.ENDC} - {size} - {model}")

    while True:
        try:
            selection = int(input(f"\n{Colors.OKBLUE}Ingresa el número del dispositivo (1-{len(drives)}): {Colors.ENDC}"))
            if 1 <= selection <= len(drives):
                return drives[selection - 1]
        except ValueError:
            pass
        print("Selección inválida.")

def flash_uboot(device_node, legacy=True):
    version = "LEGACY" if legacy else "MODERNO"
    src_file = UBOOT_LEGACY_SRC if legacy else UBOOT_MODERN_SRC
    
    if not os.path.exists(src_file):
        print(f"{Colors.FAIL}Error: No se encuentra el archivo de U-Boot {version}.{Colors.ENDC}")
        return

    print(f"\n{Colors.HEADER}>>> Flasheando U-Boot {version}...{Colors.ENDC}")
    device_path = f"/dev/{device_node}"
    
    # Comando DD específico para Allwinner (seek=8 bs=1024)
    cmd = f"dd if={src_file} of={device_path} bs=1024 seek=8 status=progress"
    
    print(f"Ejecutando: {Colors.BOLD}{cmd}{Colors.ENDC}")
    try:
        subprocess.run(cmd, shell=True, check=True)
        print(f"{Colors.OKGREEN}¡U-Boot {version} flasheado correctamente!{Colors.ENDC}")
    except subprocess.CalledProcessError:
        print(f"{Colors.FAIL}Error al flashear U-Boot.{Colors.ENDC}")

def copy_kernel(device_node):
    print(f"\n{Colors.HEADER}>>> Copiando Kernel y DTB...{Colors.ENDC}")
    
    # Asumimos partición 1 para el boot (/dev/sdb1, etc)
    part_path = f"/dev/{device_node}1"
    
    if not os.path.exists(part_path):
        print(f"{Colors.FAIL}Error: No se encuentra la partición 1 ({part_path}). Asegúrate de que la memoria esté particionada.{Colors.ENDC}")
        return

    mount_point = "/mnt/tmp_gemini_flash"
    os.makedirs(mount_point, exist_ok=True)

    # Montar
    print(f"Montando {part_path} en {mount_point}...")
    try:
        subprocess.run(["mount", part_path, mount_point], check=True)
    except subprocess.CalledProcessError:
        print(f"{Colors.FAIL}No se pudo montar la partición. ¿Tal vez hay que formatearla?{Colors.ENDC}")
        return

    try:
        # Copiar zImage
        print(f"Copiando zImage...")
        shutil.copy2(KERNEL_SRC, os.path.join(mount_point, "zImage"))
        
        # Copiar DTB
        print(f"Copiando DTB...")
        shutil.copy2(DTB_SRC, os.path.join(mount_point, "sun5i-a13-inet-86ve-rev02.dtb"))
        
        # Copiar script.bin si existe (para legacy u-boot)
        script_bin = os.path.join(WORKSPACE, "Firmware/Configs/script.bin")
        if os.path.exists(script_bin):
             print(f"Copiando script.bin (para Legacy U-Boot)...")
             shutil.copy2(script_bin, os.path.join(mount_point, "script.bin"))
        
        # Copiar boot.scr si existe (para modern u-boot)
        boot_scr = os.path.join(WORKSPACE, "U-Boot/Modern/u-boot-modern-build/boot.scr")
        if os.path.exists(boot_scr):
             print(f"Copiando boot.scr (para Modern U-Boot)...")
             shutil.copy2(boot_scr, os.path.join(mount_point, "boot.scr"))

        # Sync para asegurar escritura
        print("Sincronizando escrituras (sync)...")
        subprocess.run(["sync"])
        
        print(f"{Colors.OKGREEN}¡Archivos copiados correctamente!{Colors.ENDC}")
        
    except Exception as e:
        print(f"{Colors.FAIL}Error copiando archivos: {e}{Colors.ENDC}")
    finally:
        # Desmontar siempre
        print("Desmontando...")
        subprocess.run(["umount", mount_point])
        os.rmdir(mount_point)

def main():
    check_root()
    check_files()
    
    drives = list_drives()
    selected_drive = select_drive(drives)
    dev_name = selected_drive['name']
    
    print(f"\nHas seleccionado: {Colors.BOLD}/dev/{dev_name}{Colors.ENDC} ({selected_drive['size']})")
    print(f"{Colors.WARNING}¡ADVERTENCIA: Asegúrate de que es el dispositivo correcto!{Colors.ENDC}")
    
    print("\n¿Qué deseas hacer?")
    print("1. Copiar Kernel (zImage), DTB y Scripts")
    print("2. Flashear U-Boot LEGACY (Recomendado para A13)")
    print("3. Flashear U-Boot MODERNO (2025)")
    print("4. TODO: Legacy U-Boot + Kernel")
    print("5. TODO: Modern U-Boot + Kernel")
    print("6. Salir")
    
    opcion = input(f"\n{Colors.OKBLUE}Elige una opción: {Colors.ENDC}")
    
    if opcion == "1":
        copy_kernel(dev_name)
    elif opcion == "2":
        flash_uboot(dev_name, legacy=True)
    elif opcion == "3":
        flash_uboot(dev_name, legacy=False)
    elif opcion == "4":
        flash_uboot(dev_name, legacy=True)
        time.sleep(1)
        copy_kernel(dev_name)
    elif opcion == "5":
        flash_uboot(dev_name, legacy=False)
        time.sleep(1)
        copy_kernel(dev_name)
    else:
        print("Saliendo.")
        sys.exit(0)

    print(f"\n{Colors.OKGREEN}Proceso finalizado.{Colors.ENDC}")

if __name__ == "__main__":
    main()
