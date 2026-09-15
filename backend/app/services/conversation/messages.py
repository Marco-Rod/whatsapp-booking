MAIN_MENU = "¿Qué deseas hacer?\n1. Reservar cita"
DATES = "¿Qué día prefieres?\n1. Hoy\n2. Mañana\n3. Pasado mañana"
INVALID = "No reconocí esa opción."


def service_menu(names):
    return "¿Qué servicio deseas reservar?\n" + "\n".join(
        f"{i}. {name}" for i, name in enumerate(names, 1))


def time_menu(starts):
    return "Horarios disponibles:\n" + "\n".join(
        f"{i}. {start:%H:%M}" for i, start in enumerate(starts, 1))


def confirmation(name, start):
    return f"{name}\n{start:%Y-%m-%d %H:%M}\n¿Confirmar?\n1. Sí\n2. No"
