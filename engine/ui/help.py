"""Ausführliche Hilfetexte für die „?“-Badges (Titel, Text)."""

HELP = {
    # --- Übersicht
    "backup": ("Was macht „Backup starten“?",
               "Alle Quellen dieses Profils werden mit dem Ziel verglichen. Kopiert werden nur Dateien, die im Ziel "
               "fehlen, eine andere Größe haben oder in der Quelle neuer sind. Unveränderte Dateien werden "
               "übersprungen – deshalb ist jedes weitere Backup meist sehr schnell.\n\n"
               "Wird eine vorhandene Datei im Ziel überschrieben, wird ihre alte Version vorher als Snapshot "
               "aufbewahrt (falls Snapshots für das Profil eingeschaltet sind).\n\n"
               "Dateien, die du in der Quelle löschst, bleiben im Ziel erhalten – es wird nie etwas im Ziel gelöscht."),
    "recovery": ("Was macht „Wiederherstellen“?",
                 "Der umgekehrte Weg: Dateien werden aus dem Backup-Ziel zurück in deine Quellordner kopiert – "
                 "z. B. nach einem Festplattenschaden oder wenn du versehentlich etwas gelöscht hast.\n\n"
                 "Kopiert wird nur, was in der Quelle fehlt oder abweicht. Ist eine Datei in der Quelle neuer als im "
                 "Backup, bleibt sie standardmäßig unangetastet.\n\n"
                 "Jede überschriebene Quelldatei wird vorher gesichert. Eine Wiederherstellung lässt sich deshalb "
                 "unter „Snapshots“ wieder rückgängig machen."),
    "hdd": ("HDD-Modus",
            "Normalerweise werden mehrere Dateien gleichzeitig kopiert – das ist auf SSDs am schnellsten.\n\n"
            "Klassische Festplatten (HDD) und viele USB-Festplatten werden dadurch aber langsamer, weil der "
            "Lesekopf ständig hin- und herspringen muss. Im HDD-Modus wird deshalb eine Datei nach der anderen "
            "kopiert: für externe Festplatten meist schneller und schonender."),
    "stat_last": ("Letztes Backup",
                  "Zeitpunkt des letzten erfolgreichen Backups dieses Profils – egal ob manuell gestartet oder durch "
                  "die automatische Synchronisierung."),
    "stat_sources": ("Quellen",
                     "Anzahl der Ordner und Dateien, die in diesem Profil gesichert werden. Rot markiert sind "
                     "Quellen, die gerade nicht gefunden werden (umbenannt, gelöscht, Laufwerk nicht verbunden oder "
                     "NAS nicht erreichbar)."),
    "stat_snapshots": ("Snapshots",
                       "Anzahl der aufbewahrten Backup-Läufe dieses Profils und der Speicherplatz, den die darin "
                       "gesicherten alten Dateiversionen belegen. Ein Snapshot entsteht nur, wenn ein Lauf "
                       "tatsächlich etwas geändert hat."),
    "stat_drive": ("Ziel-Laufwerk",
                   "Freier Speicherplatz auf dem Laufwerk bzw. der Netzwerkfreigabe, auf die gesichert wird. "
                   "Grün = genug Platz, Orange = unter 15 % frei, Rot = fast voll oder nicht erreichbar."),
    "recent": ("Letzte Snapshots",
               "Die neuesten Backup-Läufe dieses Profils. Ein Klick öffnet den Lauf in der Snapshot-Liste, wo du "
               "die enthaltenen Dateien ansehen oder den Lauf zurücksetzen kannst."),
    "sync_row": ("Automatische Synchronisierung",
                 "Solange der Backup Manager läuft – auch unsichtbar im Infobereich unten rechts – werden alle "
                 "Profile, bei denen die Synchronisierung eingeschaltet ist, regelmäßig nacheinander gesichert.\n\n"
                 "„Jetzt alle synchronisieren“ startet diesen Durchlauf sofort. Ein- und ausschalten sowie den "
                 "Abstand änderst du in den Einstellungen."),
    "progress": ("Fortschritt",
                 "Erst werden alle Dateien analysiert (Vergleich Quelle ↔ Ziel), dann nur die nötigen kopiert.\n\n"
                 "Dateien: kopiert / zu kopieren\nDaten: übertragene / gesamte Datenmenge\n"
                 "Tempo: aktuelle Kopiergeschwindigkeit\nRestzeit: Schätzung anhand des Tempos\n\n"
                 "„Abbrechen“ beendet den Lauf sauber: bereits kopierte Dateien sind im Snapshot erfasst."),

    # --- Quellen & Ziel
    "sources": ("Quellen",
                "Ordner und Dateien, die gesichert werden. Ein Ordner wird im Ziel als Unterordner mit seinem Namen "
                "angelegt (D:\\Projekte\\Web → Ziel\\Web), eine einzelne Datei landet direkt im Ziel. Auch Ordner "
                "auf einem NAS (\\\\NAS\\Fotos) können Quelle sein. Systemordner von NAS und Windows (z. B. "
                "#snapshot, #recycle, @eaDir, @Recently-Snapshot, .zfs, $RECYCLE.BIN) werden automatisch "
                "übersprungen – Snapshot-Ordner enthalten sonst komplette Kopien der Freigabe.\n\n"
                "„Inhalt auswählen“ zeigt den Inhalt eines Ordners an, damit du gezielt nur bestimmte Unterordner "
                "oder Dateien hinzufügen kannst.\n\n"
                "Haben zwei Quellen denselben Namen, würden sie im Ziel im selben Ordner landen – darauf weist "
                "dich der Bereich „Hinweise“ hin."),
    "target": ("Ziel",
               "Der Ordner, in den gesichert wird – z. B. auf einer externen Festplatte, einem zweiten Laufwerk "
               "oder einem NAS im Netzwerk. Er wird beim ersten Backup automatisch angelegt.\n\n"
               "Netzwerk (Synology, QNAP, FRITZ!Box, TrueNAS, Windows-Freigaben …): Pfad wie \\\\NAS\\Backup\\PC "
               "oder \\\\192.168.178.20\\Backup eintippen, über die Ordnerauswahl links „Netzwerk“ wählen oder ein "
               "verbundenes Netzlaufwerk (z. B. Z:) nutzen. Braucht die Freigabe ein Passwort, erscheint „Am NAS "
               "anmelden …“ – mit „Anmeldedaten speichern“ klappt es danach auch bei der automatischen "
               "Synchronisierung. Windows 11 erlaubt keinen Gastzugang ohne Passwort mehr; nutze ein Benutzerkonto "
               "des NAS.\n\n"
               "Ist das NAS gerade aus oder wacht noch auf, wartet ein Backup bis zu einer Minute darauf. Bricht "
               "die Verbindung mitten im Lauf ab, wird er sauber beendet und beim nächsten Mal fortgesetzt.\n\n"
               "Der Balken zeigt, wie voll das Laufwerk ist. Vor jedem Backup wird geprüft, ob genug Platz für die "
               "neuen Dateien und die Snapshots vorhanden ist – sonst startet es gar nicht erst."),
    "snapshots_option": ("Snapshots anlegen",
                         "Eingeschaltet (empfohlen): Bevor eine Datei im Ziel überschrieben wird, wird die alte "
                         "Version im Snapshot-Ordner aufbewahrt. So kannst du jeden Lauf zurücksetzen oder einzelne "
                         "ältere Dateiversionen zurückholen.\n\n"
                         "Ausgeschaltet: Das Ziel ist immer eine reine Kopie des aktuellen Stands. Das spart "
                         "Speicherplatz, aber beim Überschreiben gehen ältere Versionen verloren und ein Zurücksetzen "
                         "ist nicht möglich. Bereits vorhandene Snapshots bleiben erhalten."),
    "auto_sync_profile": ("In automatische Synchronisierung einbeziehen",
                          "Ist die automatische Synchronisierung in den Einstellungen aktiv, wird dieses Profil im "
                          "eingestellten Abstand (z. B. alle 60 Minuten) automatisch gesichert.\n\n"
                          "Ist das Ziel gerade nicht erreichbar (externe Festplatte nicht angeschlossen, NAS "
                          "ausgeschaltet), wird das Profil übersprungen und beim nächsten Durchlauf erneut versucht."),
    "excludes": ("Ausschließen",
                 "Dateien und Ordner, die nicht gesichert werden sollen – ein Muster pro Zeile:\n\n"
                 "• .git, node_modules, __pycache__ – Ordner mit diesem Namen (überall)\n"
                 "• *.tmp, *.log – alle Dateien mit dieser Endung\n"
                 "• ~$* – Sperrdateien von Office\n"
                 "• logs/archiv – genau dieser Unterordner (relativ zur Quelle)\n\n"
                 "Groß-/Kleinschreibung spielt keine Rolle. Schon im Ziel vorhandene Dateien werden dadurch nicht "
                 "gelöscht. „Vorschläge“ fügt übliche Muster für Entwicklerordner ein."),
    "issues": ("Hinweise",
               "Automatische Prüfung deiner Einstellungen – z. B. fehlende Quellen, nicht verbundenes Ziel-Laufwerk "
               "oder zwei Quellen mit gleichem Namen. Rot = sollte behoben werden, Orange = bitte prüfen, "
               "Blau = nur zur Info."),

    # --- Snapshots
    "snapshots_page": ("Was sind Snapshots?",
                       "Jedes Mal, wenn ein Backup eine Datei im Ziel überschreibt, wird die alte Version vorher "
                       "gesichert. Alle so gesicherten Versionen eines Laufs bilden einen Snapshot.\n\n"
                       "Damit kannst du einen kompletten Lauf zurücksetzen oder über „Details“ einzelne ältere "
                       "Dateiversionen speichern."),
    "scope": ("Dieses Profil / Alle Profile",
              "„Dieses Profil“ zeigt nur die Snapshots des links ausgewählten Profils.\n\n"
              "„Alle Profile“ zeigt zusätzlich Snapshots gelöschter Profile und alter Programmversionen – praktisch, "
              "um aufzuräumen."),
    "snapshot_status": ("Spalten und Status",
                        "Neu – Dateien, die es vorher im Ziel nicht gab (werden beim Zurücksetzen gelöscht).\n"
                        "Geändert – überschriebene Dateien, deren alte Version gesichert wurde.\n"
                        "Größe – Speicherplatz der gesicherten alten Versionen.\n\n"
                        "Status:\n"
                        "OK – alles vorhanden, vollständig zurücksetzbar.\n"
                        "Teilweise – einige Snapshot-Dateien fehlen (z. B. manuell gelöscht).\n"
                        "Fehlend – keine Snapshot-Dateien mehr vorhanden.\n"
                        "Leer – der Lauf enthält keine Dateien.\n\n"
                        "Zusätze: „abgebrochen“ = vorzeitig beendet, „zurückgesetzt“ = bereits einmal "
                        "zurückgesetzt, „unvollständig“ = Programm wurde während des Laufs beendet."),
    "rollback": ("Zurücksetzen",
                 "Stellt den Zustand vor diesem Lauf wieder her: Überschriebene Dateien werden aus dem Snapshot "
                 "zurückkopiert, in diesem Lauf neu angelegte Dateien gelöscht. Vorher siehst du eine genaue "
                 "Vorschau.\n\nBei einem Snapshot der Art „Wiederherstellung“ werden stattdessen deine Quellordner "
                 "auf den Stand vor der Wiederherstellung gebracht."),
    "prune": ("Aufräumen",
              "Löscht ältere Snapshots dieses Profils und behält nur die neuesten. Die aktuellen Dateien im Ziel "
              "bleiben unverändert – es gehen nur die aufbewahrten alten Versionen verloren.\n\n"
              "In den Einstellungen kannst du das automatische Aufräumen nach jedem Backup einschalten."),

    # --- Protokoll
    "log": ("Protokoll",
            "Alle Meldungen seit dem Programmstart. Mit dem Filter siehst du nur Warnungen (z. B. nicht gefundene "
            "Quellen) oder Fehler (z. B. gesperrte Dateien). Frühere Sitzungen liegen als Textdateien im "
            "Log-Ordner."),

    # --- Einstellungen
    "appearance": ("Farbschema",
                   "Hell, Dunkel oder „System“ – dann richtet sich der Backup Manager automatisch nach der "
                   "Windows-Einstellung."),
    "autostart": ("Mit Windows starten",
                  "Der Backup Manager startet beim Anmelden automatisch – unsichtbar im Infobereich der Taskleiste "
                  "(unten rechts neben der Uhr, eventuell hinter dem kleinen Pfeil ^ versteckt). Ein Klick auf das "
                  "Symbol öffnet das Fenster.\n\nDer Eintrag gilt nur für deinen Windows-Benutzer und braucht keine "
                  "Administratorrechte."),
    "auto_sync": ("Automatisch synchronisieren",
                  "Solange der Backup Manager läuft (auch im Infobereich), werden alle Profile mit eingeschalteter "
                  "Synchronisierung im eingestellten Abstand nacheinander gesichert – ohne dass du etwas tun musst.\n\n"
                  "Nicht angeschlossene Laufwerke und nicht erreichbare NAS werden übersprungen. Wurden Dateien "
                  "gesichert oder gab es Fehler, "
                  "erscheint eine kurze Windows-Benachrichtigung.\n\n"
                  "Ob ein Profil mitmacht, stellst du unter „Quellen & Ziel → Optionen“ ein."),
    "interval": ("Abstand",
                 "Wie oft synchronisiert wird. Der erste Durchlauf startet etwa zwei Minuten nach dem Programmstart, "
                 "danach im gewählten Abstand. Da nur geänderte Dateien kopiert werden, sind häufige Durchläufe "
                 "meist schnell."),
    "close_to_tray": ("Beim Schließen in den Infobereich",
                      "Ein Klick auf das X beendet das Programm nicht, sondern blendet das Fenster aus. Der Backup "
                      "Manager läuft im Infobereich weiter, damit die automatische Synchronisierung funktioniert.\n\n"
                      "Vollständig beenden: Rechtsklick auf das Symbol im Infobereich → „Beenden“."),
    "update_check": ("Automatisch nach Updates suchen",
                     "Einmal täglich fragt der Backup Manager bei GitHub nach, welches die neueste Version ist. Dabei "
                     "werden keine Daten über dich oder deine Backups übertragen.\n\n"
                     "Gibt es eine neue Version, erscheint ein Hinweis (im Infobereich als Windows-Benachrichtigung). "
                     "„Jetzt aktualisieren“ lädt den Installer, prüft seine Echtheit anhand der Prüfsumme von GitHub "
                     "und installiert ihn. Profile, Einstellungen und Snapshots bleiben erhalten.\n\n"
                     "Ausgeschaltet geht der Backup Manager nie von selbst ins Internet; „Jetzt prüfen“ funktioniert "
                     "trotzdem."),
    "workers": ("Parallele Kopiervorgänge",
                "Wie viele Dateien gleichzeitig kopiert werden. Mehr ist auf SSDs und schnellen Laufwerken "
                "schneller; bei klassischen Festplatten besser den HDD-Modus im Profil nutzen (dann wird immer "
                "nacheinander kopiert)."),
    "auto_prune": ("Alte Snapshots automatisch löschen",
                   "Nach jedem erfolgreichen Backup werden nur die neuesten Snapshots des Profils behalten (Anzahl "
                   "siehe unten), ältere werden gelöscht. Verhindert, dass Snapshots unbemerkt die Festplatte füllen."),
    "keep": ("Anzahl behalten",
             "So viele Snapshots pro Profil bleiben beim Aufräumen erhalten – sowohl beim automatischen Aufräumen "
             "als auch als Vorschlag beim manuellen „Aufräumen“ auf der Snapshot-Seite."),
    "versions_dir": ("Speicherort der Snapshots",
                     "Hier liegen die alten Dateiversionen aller Profile. Snapshots können viel Platz belegen – wähle "
                     "bei Bedarf ein Laufwerk mit genug freiem Speicher.\n\nBeim Ändern werden die vorhandenen "
                     "Snapshots in den neuen Ordner verschoben."),
    "confirm_close": ("Beim Beenden nachfragen",
                      "Sicherheitsabfrage, bevor das Programm wirklich beendet wird."),
}
