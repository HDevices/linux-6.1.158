setenv bootargs console=ttyS0,115200 console=tty1 root=/dev/mmcblk0p2 rootwait panic=10
load mmc 0:1 ${kernel_addr_r} zImage
load mmc 0:1 ${fdt_addr_r} sun5i-a13-inet-86ve-rev02.dtb
bootz ${kernel_addr_r} - ${fdt_addr_r}
