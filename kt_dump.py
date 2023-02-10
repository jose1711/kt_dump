#!/usr/bin/env python
'''
Skript pre stiahnutie štatistík z kaloricketabulky.sk a ich uloženie do Excel súboru.

'''
import PySimpleGUI as sg
from datetime import datetime, timedelta
from hashlib import md5
from pprint import pprint
import matplotlib.pyplot as plt
import queue
import pandas as pd
import requests
import sys
import threading

sg.theme('BlueMono')


def get_data(user, password, start, end, output, q):
    start = datetime.strptime(start, '%Y-%m-%d')
    end = datetime.strptime(end, '%Y-%m-%d')
    
    md5_password = md5(password.encode()).hexdigest()
    
    s = requests.Session()
    s.get('https://www.kaloricketabulky.sk')
    s.post('https://www.kaloricketabulky.sk/login/create?=&format=json',
            json={'email': user,
                  'password': md5_password})
    
    if not s.cookies.get('kaloricketabulky_token'):
        q.put([False, ['Chyba pri prihlasovaní', 'Zadali ste správne heslo?']])
        return
    
    def get_nutrients_data(data):
        ret = []
        for attr in ('protein',
                     'carbohydrate',
                     'sugar',
                     'fat',
                     'saturatedFattyAcid',
                     'fiber'):
            ret.append(data['list'][-1].get(attr))
        return ret
    
    def get_optional_data(data):
        return []
    
    nut_url = 'https://www.kaloricketabulky.sk/statistic/analysis/table/{date}/{date}/get?format=json'
    wgt_url = 'https://www.kaloricketabulky.sk/statistic/weight/{date}/{date}/get?format=json'
    opt_url = 'https://www.kaloricketabulky.sk/statistic/optional/{date}/{date}/get?format=json'
    
    nutrients = []
    energy = []
    weight = []
    
    # get nutrients and weight data
    for n in range((end - start).days):
        day = (start + timedelta(n)).strftime('%d.%m.%Y')
        print(n, day)
        r = s.get(wgt_url.format(date=day))
        try:
            data = r.json()['data']
        except Exception as e:
            print('Error parsing JSON. Maybe we can ignore this?')
            continue
        if data.get('values'):
            weight_value = data['values'][0]['value']
            weight.append([day, weight_value])
    
    
    # get weight data
    for n in range((end - start).days):
        day = (start + timedelta(n)).strftime('%d.%m.%Y')
        print(n, day)
        r = s.get(nut_url.format(date=day))
        data = r.json()['data']
        nutrients_data = get_nutrients_data(data)
        nutrients.append([day] + nutrients_data)
    
        energy_in = data['list'][-3]['energy']/4.184
        energy_out = data['list'][-2]['energy']/4.184
        energy_diff = energy_in - energy_out
        energy.append([day] + [energy_in, energy_out, energy_diff])
    
    
    # get optional data
    for n in range((end - start).days):
        day = (start + timedelta(n)).strftime('%d.%m.%Y')
        print(n, day)
        r = s.get(opt_url.format(date=day))
        data = r.json()['data']
        optional_data = get_optional_data(data)
        optional_data.append([day] + optional_data)
    
    # nutrients
    df_nut = pd.DataFrame(nutrients,
                          columns=('date', 'protein', 'carbohydrate', 'sugar', 'fat', 'saturatedFattyAcid', 'fiber'))
    df_nut.set_index('date', inplace=True)
    
    # energy
    df_ene = pd.DataFrame(energy,
                          columns=('date', 'energy_in', 'energy_out', 'energy_diff'))
    df_ene.set_index('date', inplace=True)
    
    # weight
    df_wgt = pd.DataFrame(weight,
                          columns=('date', 'weight'))
    df_wgt.set_index('date', inplace=True)
    df_wgt.ffill(inplace=True)
    
    df_all = df_nut.join(df_wgt).join(df_ene)
    df_all.ffill(inplace=True)
    ax = df_all.plot()
    ax = df_all.weight.plot()
    ax1 = ax.twinx()
    
    df_all.weight.plot(ax=ax1, color='r')
    plt.show()
    df_all.to_excel(output)
    
    df_enewgt = df_ene.join(df_wgt)
    df_enewgt.ffill(inplace=True)
    df_enewgt.set_index(pd.to_datetime(df_enewgt.energy_in.index, format='%d.%m.%Y'), inplace=True)

    ax = df_enewgt.energy_in.interpolate(method='pchip', time=5).plot()
    ax1 = ax.twinx()
    df_enewgt.weight.plot(ax=ax1, color='r')
    plt.show()
    q.put([True, '', ''])


layout = [[sg.Text('Meno používateľa'), sg.In(key='-username-')],
          [sg.Text('Heslo'), sg.In(key='-password-')],
          [sg.In(key='-start-', disabled=True, size=(10, 1)),
           sg.CalendarButton('Začiatok', target='-start-', format='%Y-%m-%d', close_when_date_chosen=True),
           sg.In(key='-end-', disabled=True, size=(10, 1)),
           sg.CalendarButton('Koniec', target='-end-', format='%Y-%m-%d', close_when_date_chosen=True)],
          [sg.Text('Výstup', key='-out-'), sg.FileSaveAs(button_text='Uložiť ako..', key='-output-', target='-out-')],
          [sg.OK()]]

thread = None
q = queue.Queue()
orig_ok_button_color = sg.OK().ButtonColor

window = sg.Window(title='Kalorické tabuľky - Excel export', layout=layout)
while True:
    event, values = window.read(timeout=250)
    if event == sg.WIN_CLOSED:
        if thread:
            thread.join()
        break
    elif event == 'OK':
        args = [values.get(x) for x in ('-username-', '-password-', '-start-', '-end-', '-output-')] + [q]
        if all(args):
           thread = threading.Thread(target=get_data, args=args)
           thread.start()
        else:
            sg.Popup('Musíte vyplniť všetky polia!')

    if thread and thread.is_alive():
        window['OK'].update(disabled=True, text='Čakajte, prosím..', button_color=orig_ok_button_color)
    elif thread:
        try:
            thread_output = q.get(block=True, timeout=60)
        except:
            sg.Popup('Neznáma chyba', 'Vyskytla sa neošetrená chyba, skúste zmenšiť interval medzi dňami alebo pokus opakujte neskôr.')
            thread = None
            continue

        if not thread_output[0]:
            sg.Popup(thread_output[1][1], title=thread_output[1][0])
        else:
            sg.Popup(f'Výstup nájdete v súbore {values.get("-output-")}', title='Hotovo!')
        thread = None
    else:
        window['OK'].update(disabled=False, text='OK', button_color=orig_ok_button_color)
