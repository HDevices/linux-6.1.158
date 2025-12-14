# Documentación: Manejo del LCD en iNet 86VE rev02 (kernel funcional 6.1.158)

> Objetivo: documentar cómo el kernel antiguo (6.1.158, funcional) maneja el LCD, tcon, backlight y dependencias (PMIC AXP209, pinctrl, reguladores). Recopilar evidencia, mapa de nodos DT, causas de deferred-probe y pasos reproducibles.

---

## 1. Resumen ejecutivo

El kernel 6.1.158 arranca correctamente y detecta el PMIC AXP209 por I²C, la GPU (lima) y el MMC; sin embargo, los nodos relacionados con la pantalla (`reg-vcc-lcd`, `reg-bl-en`, `backlight`, `1c0c000.lcd-controller`) quedan en `deferred probe`. Los mensajes clave indican que el `pinctrl` no encuentra ciertas supplies (por ejemplo `vcc-pb`, `vcc-pg`, `vcc-pf`) y por ello usa `dummy regulator`, lo que provoca que la configuración del controlador de LCD/tcon se posponga.

Esto sugiere un desajuste entre los phandles/supply names que espera el árbol de dispositivo del SoC (sun5i include) y los reguladores/labels expuestos por el PMIC en el DT de la placa.

---

## 2. Evidencia (extractos del dmesg)

```
[    0.153323] sun5i-pinctrl 1c20800.pinctrl: initialized sunXi PIO driver
[    0.154966] sun5i-pinctrl 1c20800.pinctrl: supply vcc-pb not found, using dummy regulr
[    0.219066] sun5i-pinctrl 1c20800.pinctrl: supply vcc-pg not found, using dummy regulr
[    0.900236] axp20x-i2c 0-0034: AXP20x variant AXP209 found
[    0.951039] axp20x-adc: Failed to locate of_node [id: -1]
[    0.956636] axp20x-battery-power-supply: Failed to locate of_node [id: -1]
[    0.963702] axp20x-ac-power-supply: Failed to locate of_node [id: -1]
[    0.970291] axp20x-usb-power-supply: Failed to locate of_node [id: -1]
[    0.976923] axp20x-i2c 0-0034: AXP20X driver loaded
[   11.372363] platform reg-vcc-lcd: deferred probe pending
[   11.382999] platform backlight: deferred probe pending
[   11.388153] platform 1c0c000.lcd-controller: deferred probe pending
```

**Interpretación:** el driver axp20x carga (AXP209 detectado), pero las sub-nodos auxiliares (adc, power-supplies) no se encuentran con su of_node (esto es normal si no se añadieron phandles para ciertas `power-supply` nodes). `pinctrl` reclama supplies que no existen en el DT de la placa.

---

## 3. Mapa de nodos relevantes (DT del usuario)

Los nodos importantes que aparecen en tu DTS son:

- `/soc/i2c@.../pmic@34` (axp209) — actualmente incluido desde `axp209.dtsi` con overrides en `&axp209`.
- `/reg-vcc-lcd` y `/reg-bl-en` — definidos en root como `regulator-fixed` con `gpio = <&axp_gpio ...>`.
- `panel` (compatible = "simple-panel") y `lcd_backlight` (compatible = "pwm-backlight").
- `&pio` pinctrl con `lcd-rgb-pins` function = "lcd0".
- `&tcon0` que referencia `vcc-lcd-supply = <&reg_vcc_lcd>`.

Puntos críticos:
- `pinctrl` (sun5i-pinctrl) espera phandles `vcc-pb-supply`, `vcc-pg-supply`, `vcc-pf-supply` (nombres que vienen del include SoC) y si no los encuentra, usa dummy regulator.
- Tus `reg_vcc_lcd` y `reg_bl_en` dependen de `&axp_gpio` (control vía PMIC GPIO) — si `axp_gpio` no está disponible (status != "okay") el `regulator-fixed` que referencia `&axp_gpio` queda en deferred.

---

## 4. Hipótesis de raíz

1. Falta mapear en la raíz del DT los supply phandles que `sun5i` pinctrl y otros controladores esperan (por ejemplo `vcc-pb-supply`, `vcc-pg-supply`, `vcc-pf-supply`).
2. Aunque el driver AXP209 se carga, los sub-nodos que exponen `power-supply` (ADC, battery, usb) no están presentes porque no añadiste esos nodos o phandles; los drivers del kernel esperan poder crear `power_supply` udev nodes y fallan el lookup si el binding no está completo.
3. `axp_gpio` puede no estar marcado `status = "okay"` en el override, o los labels en el `axp209.dtsi` no coinciden con los usados como phandles en el resto del DTS.

---

## 5. Qué buscar en el kernel fuente (comandos)

Usa estos comandos en el árbol del kernel para encontrar los controladores/bindings relevantes y sus drivers:

```bash
# Buscar drivers PMIC AXP
grep -R "axp20x" -n drivers || true
# Buscar pinctrl sunxi
grep -R "sun5i-pinctrl\|sunxi-pinctrl" -n drivers || true
# Buscar tcon / lcd / backlight drivers
grep -R "tcon\|lcd-controller\|pwm-backlight\|simple-panel" -n drivers || true

# Inspeccionar bindings de device tree
grep -R "vcc-pb-supply\|vcc-pg-supply\|vcc-pf-supply" -n Documentation device-tree || true

# Si quieres obtener ficheros exactos a inspeccionar:
# - drivers/power/pmic/axp20x*.c
# - drivers/gpio/axp20x-gpio* (si existe)
# - drivers/pinctrl/sunxi/ (controlador pinctrl)
# - drivers/gpu/drm/lima (Mali 400)
# - drivers/video/sunxi* (lcd/tcon platform drivers)
```

> Nota: si no estás seguro de nombres de archivo, usa `grep -R` como arriba para localizar los ficheros exactos en tu árbol.

---

## 6. Checklist de pruebas y comandos (para documentar reproducibles)

Ejecuta y anota salidas para cada paso (para reproducibilidad):

1. Comprobar que el AXP se detecta en I²C y el driver carga:

```bash
dmesg | grep -i axp
# o
i2cdetect -y -r 0  # si i2c-tools está en rootfs
```

2. Listar nodos del device-tree relevantes:

```bash
# Mostrar label/hardware nodes
ls -l /proc/device-tree
hexdump -C /proc/device-tree/ | head
# Inspeccionar existence de phandles que añadiste
hexdump -C /proc/device-tree/vcc-pb-supply || echo no_vcc-pb
```

3. Revisar backlight/sysfs:

```bash
ls /sys/class/backlight || true
cat /sys/class/backlight/*/max_brightness 2>/dev/null || true
```

4. Buscar deferred probe y orden de probe:

```bash
dmesg | grep -i "deferred probe"
# Para más contexto, show entire dmesg and search for the controller names
```

5. Revisar que `axp_gpio` se crea:

```bash
dmesg | grep -i gpio | grep -i axp || true
ls /sys/class/gpio || true
```

6. Si compilas un nuevo DTB, compara `dtc -I dtb -O dts` del DTB en /boot con tu DTS fuente para comprobar labels y phandles reales:

```bash
dtc -I dtb -O dts /boot/sun5i-a13-inet-86ve-rev02.dtb > /tmp/compiled.dts
sed -n '1,240p' /tmp/compiled.dts
```

---

## 7. Recomendaciones (resumen técnico)

1. **Documentar el árbol DT actual del kernel funcional**: compila DTB de tu árbol y `dtc -I dtb -O dts` para crear la "versión canónica" del DT que realmente se usa en el kernel funcional. Añádela a la documentación.
2. **Registrar diferencias entre tu DTS fuente y DTB compilado**: anotar labels y phandles que cambien o se pierdan.
3. **Documentar mapa de supplies que pinctrl y tcon esperan**: extraer nombres exactos desde `sun5i-a13.dtsi`/includes y mapearlos contra los labels de `axp209.dtsi`.
4. **Añadir sección "por qué deferred probe"** con la explicación del orden de probe y la necesidad de `regulator-boot-on` o `status = \"okay\"` para reguladores críticos.
5. **Generar una tabla** con: `driver kernel`, `node DT`, `supply/phandle required`, `current DT mapping`, `acción recomendada`.

---

## 8. Propuesta de índice para la documentación final

1. Resumen ejecutivo
2. Hardware (esquema, fotos, pines relevantes)
3. Árbol de dispositivo (DTS fuente + DTB compilado)
4. Logs de arranque relevantes (filtrados)
5. Análisis de drivers involucrados
   - AXP209 (axp20x)
   - pinctrl sun5i
   - tcon/lcd driver
   - pwm-backlight
6. Mapa de supplies/phandles y correspondencias
7. Lista de cambios aplicados al DTS y su razón
8. Experimentos realizados y resultados (comandos y salidas)
9. Recomendaciones para parches y próximos pasos
10. Apéndices (grep outputs, diffs, dtc outputs)

---

## 9. Plantilla de entrada (para que rellenes con salidas reales)

```
# Fecha: YYYY-MM-DD
# Kernel: 6.1.158-g4d4166ab7301-dirty
# DTB usado: /boot/sun5i-a13-inet-86ve-rev02.dtb

## dmesg relevante:
<pega aquí>

## dtc compiled.dts:
<pega aquí>

## Resultado de `ls /sys/class/backlight`:
<pega aquí>

## Resultado de `dmesg | grep -i "deferred probe"`:
<pega aquí>
```

---

## 10. Próximos pasos concretos que puedo generar para ti ahora

- Generar la **documentación completa en Markdown** (basada en este template) con secciones llenas y textos explicativos — listos para commit en tu repo.  
- Crear un **diff/patch** con los cambios de DTS que ya aplicaste (include axp209, overrides, status) y una versión alternativa que en lugar de `regulator-fixed` use directamente LDOs del AXP para `vcc-lcd`.  
- Preparar una **guía de debugging** paso-a-paso con comandos y cómo interpretar los outputs.  

Si quieres que genere la documentación completa (archivo Markdown) con lo que ya tenemos y con placeholders para los outputs pendientes, puedo crearla ahora y dejarla en tu workspace lista para que pegues las salidas.  

---

*Generado automáticamente como punto de partida. Actualiza con logs y salidas del sistema para completar la documentación.*

