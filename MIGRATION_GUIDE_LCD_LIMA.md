# Guía de Migración: LCD y GPU Lima (Legacy a Mainline 6.x)
**Dispositivo:** Allwinner A13 Tablet (Board: inet-86ve / A13-EVB-V1.0)
**Objetivo:** Habilitar pantalla LCD RGB y aceleración 3D (Lima) en Kernel 6.1 LTS.

---

## 1. Análisis del Hardware (Origen: script.fex)

Datos extraídos de la configuración original de fábrica (`[lcd0_para]`).

| Parámetro | Valor Original (FEX) | Notas |
| :--- | :--- | :--- |
| **Resolución** | 800 x 480 | |
| **Frecuencia (Clock)** | 33 MHz | `lcd_dclk_freq = 33` |
| **Interfaz** | RGB888 (24 bits) | Pines PD0-PD23 (`lcd_hv_if = 0`) |
| **PWM Backlight** | PB02 | `lcd_pwm` |
| **PWM Frecuencia** | 10kHz | `lcd_pwm_freq = 10000` |

### Pines de Datos (Puerto D)
El bus de datos usa **24 pines** (RGB888), lo que significa que usa todo el puerto PD:
- `lcdd0` - `lcdd23` -> `PD0` - `PD23`
- `lcdclk` -> `PD24`
- `lcdde` (Data Enable) -> `PD25`
- `lcdhsync` -> `PD26`
- `lcdvsync` -> `PD27`

---

## 2. Traducción de Timings (FEX a DRM/KMS)

El kernel moderno usa el concepto de "Front Porch" en lugar de "Total".
**Fórmula:** `Front Porch = Total - Active - Back Porch - Pulse Width`

### Horizontal
*   **Total (HT):** 1055
*   **Active (X):** 800
*   **Back Porch (HBP):** 46
*   **Sync Pulse (HSPW):** 30
*   **Front Porch (HFP):** `1055 - 800 - 46 - 30` = **179**

### Vertical
*   **Total (VT):** 1050
*   **Active (Y):** 480
*   **Back Porch (VBP):** 23
*   **Sync Pulse (VSPW):** 1
*   **Front Porch (VFP):** `1050 - 480 - 23 - 1` = **546**

> **⚠️ NOTA CRÍTICA:** El `VFP` calculado (546) es inusualmente alto. Esto indica un "Vertical Blanking" muy largo en el driver original.
> *Estrategia:* Probar primero con estos valores exactos. Si la pantalla parpadea o se desincroniza en Mainline, reducir `VFP` y recalcular el reloj de pixel.

---

## 3. Implementación Teórica (Device Tree)

Agregar estos fragmentos al archivo `.dts` de la placa (ej. `sun5i-a13-inet-86v.dts`).

### A. Nodo del Panel
```dts
panel {
    compatible = "panel-dpi";
    label = "lcd-800x480-inet";
    
    /* Gestión de energía */
    power-supply = <&reg_vcc3v3>; /* Verificar si requiere regulador específico */
    backlight = <&backlight>;

    port {
        panel_input: endpoint {
            remote-endpoint = <&tcon0_out_lcd>;
        };
    };

    panel-timing {
        clock-frequency = <33000000>; /* 33 MHz */
        
        hactive = <800>;
        vactive = <480>;
        
        /* Horizontal */
        hback-porch = <46>;
        hfront-porch = <179>;
        hsync-len = <30>;
        
        /* Vertical */
        vback-porch = <23>;
        vfront-porch = <546>; /* Valor crítico */
        vsync-len = <1>;
        
        /* Polaridad (0 = activo bajo/estándar para DPI) */
        hsync-active = <0>;
        vsync-active = <0>;
        de-active = <1>;
        pixelclk-active = <1>;
    };
};
```

### B. Pipeline de Video (TCON0)
```dts
&tcon0 {
    pinctrl-names = "default";
    /* Usar rgb888 si está definido en dtsi, si no rgb666 y descartar bits bajos */
    pinctrl-0 = <&lcd_rgb888_pins>; 
    status = "okay";
};

&tcon0_out {
    tcon0_out_lcd: endpoint {
        remote-endpoint = <&panel_input>;
    };
};
```

### C. Backlight (PWM en PB02)
```dts
&pwm {
    pinctrl-names = "default";
    pinctrl-0 = <&pwm0_pins>;
    status = "okay";
};

backlight: backlight {
    compatible = "pwm-backlight";
    pwms = <&pwm 0 100000 0>; /* PWM0, 100kns periodo (10kHz) */
    brightness-levels = <0 10 20 30 40 50 60 70 80 90 100>;
    default-brightness-level = <8>;
};
```

### D. GPU Lima (Aceleración 3D)
El nodo `mali` ya existe en `sun5i-a13.dtsi`, solo debemos activarlo.

```dts
&mali {
    status = "okay";
};
```

---

## 4. Configuración del Kernel (make menuconfig)

Para que esto funcione, el kernel debe compilarse con estas opciones:

1.  **Device Drivers -> Graphics support:**
    *   `CONFIG_DRM = y`
    *   `CONFIG_DRM_SUN4I = m` (Display Engine)
    *   `CONFIG_DRM_LIMA = m` (GPU Mali-400)
    *   `CONFIG_DRM_PANEL_SIMPLE = y` (o `CONFIG_DRM_PANEL_DPI`)

2.  **Memory Management:**
    *   `CONFIG_DMA_CMA = y`
    *   `CONFIG_CMA_SIZE_MBYTES = 64` (Mínimo recomendado para Lima)

---

## 5. Verificación Post-Boot

1.  **Pantalla:** Debería mostrar la consola de Linux (`fb0`) al arrancar.
2.  **GPU:**
    *   Comando: `dmesg | grep lima` -> Debería mostrar inicialización exitosa.
    *   Comando: `glxinfo | grep renderer` -> Debería decir "Mali400" o "Lima".

---

## 6. Análisis del PMIC (AXP209)

El chip AXP209 gestiona toda la energía de la tablet. La configuración se ha deducido combinando `script.fex`, el código fuente del driver `axp20-board.c` y **mediciones físicas en placa**.

| Regulador | Nombre Interno | Voltaje (FEX) | Uso Confirmado | Notas |
| :--- | :--- | :--- | :--- | :--- |
| **DCDC2** | `axp20_core` | **1.40V** | **VDD-CPU** | Escala dinámicamente con la frecuencia CPU. |
| **DCDC3** | `axp20_ddr` | **1.20V** | **VDD-INT / DLL** | Voltaje lógico interno y memoria. |
| **LDO1** | `axp20_rtc` | 1.3V (fijo) | RTC (Reloj) | Siempre activo. |
| **LDO2** | `axp20_analog` | **3.00V** | Audio Codec / Sensores | AVCC. |
| **LDO3** | `axp20_pll` | **3.30V** | **LCD VCC (Power)** | **Confirmado por medición.** Alimenta el panel. |
| **LDO4** | `axp20_hdmi` | **3.30V** | Touchscreen (CTP) / USB | Reutilizado (A13 no tiene HDMI). |

### Señales de Control Confirmadas
*   **PWM Backlight:** Pin `PB02` (Pin CPU 103). Medido a **1.9V** con brillo medio (aprox 57% duty cycle de 3.3V).
*   **Backlight Enable:** `port:power1` corresponde a **AXP209 GPIO 1**. Debe configurarse como salida en el nodo del PMIC.

### Implementación en Device Tree (Kernel 6.x)
En el nodo del AXP209 (`&i2c0 -> axp209`), definir:

```dts
&axp209 {
    /* Configurar GPIO1 como salida para habilitar backlight */
    gpio1_out: gpio-controller {
        #gpio-cells = <2>;
        gpio-controller;
    };
};

&reg_ldo3 {
    regulator-always-on; /* O controlado por power-supply del LCD */
    regulator-min-microvolt = <3300000>;
    regulator-max-microvolt = <3300000>;
    regulator-name = "vcc-lcd";
};
```

Y en el nodo `panel`:
```dts
panel {
    /* ... */
    /* Enable conectado a GPIO1 del AXP209 */
    enable-gpios = <&axp_gpio 1 GPIO_ACTIVE_HIGH>; 
};
```

---

## 7. Secuencia de Arranque (Legacy vs Moderno)

### Legacy (Debian Wheezy / Kernel 3.4)
El sistema gráfico **no** se iniciaba automáticamente por el kernel.
1.  **Bootloader:** U-Boot carga kernel y script.bin.
2.  **Kernel:** Inicializa framebuffer básico (`fb0`).
3.  **Init:** `sysvinit` ejecuta `/etc/rc.local`.
4.  **RC.Local:**
    *   `chmod 777 /dev/disp /dev/mali`: Da permisos globales al hardware.
    *   `/etc/init.d/lightdm start`: Lanza el gestor gráfico manualmente.

### Moderno (Debian Bullseye+ / Kernel 6.x)
Todo esto se estandariza.
1.  **Kernel (DRM/KMS):** Inicializa la pantalla durante el boot (log de pingüinos visible a los pocos segundos).
2.  **Systemd:** Lanza el Display Manager (LightDM/GDM) automáticamente cuando el dispositivo DRM está listo.
3.  **Permisos:** Gestionados por grupos (`video`, `render`) y reglas udev, sin necesidad de `chmod 777`.

