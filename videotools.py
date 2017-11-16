#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import time
import math
import os
import re
import subprocess
import getopt
import sys
import logging

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gtk, GObject, GLib

from lxml import etree as ET
from threading import Thread
from glob import glob
from distutils import spawn


class VideoProgressDialog(Gtk.Dialog):
    must_stop = False
    failed = False
    params = []
    sufixoArquivo = "modificado.mp4"
    arquivoDestino = None
    segundosTotal = 0
    segundosConcluidos = 0

    def __init__(self, parent, arquivos, destino, titulo, params, sufixoArquivo, arquivoDestino, segundosTotal):
        Gtk.Dialog.__init__(self, titulo, parent, 0,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL))

        self.set_size_request(250, 150)
        self.set_border_width(10)

        self.lista_arquivos = arquivos
        self.dir_destino = destino
        self.params = params
        self.sufixoArquivo = sufixoArquivo
        self.arquivoDestino = arquivoDestino
        self.segundosTotal = segundosTotal

        # Container principal
        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        grid.set_column_spacing(4)
        grid.set_row_spacing(6)

        # Força entrar no loop se o arquivo de destino foi especificado
        if self.arquivoDestino is not None:
            self.lista_arquivos = [self.arquivoDestino]

        totalBytes = 0
        for arquivo in self.lista_arquivos:
            if os.path.isfile(arquivo):
                totalBytes += os.stat(arquivo).st_size
            
        # Label com o título da atividade
        grid.attach(Gtk.Label(label="Efetuando o processamento de " + str(len(self.lista_arquivos)) + 
                              " vídeos - " + seconds_to_time(segundosTotal) + " (" + human_size(totalBytes) + ")", halign=Gtk.Align.START), 0, 0, 6, 1)

        # Progresso total
        self.progress_bar_total = Gtk.ProgressBar(show_text=True)
        grid.attach(self.progress_bar_total, 0, 1, 6, 1)

        # Titulo de info do progresso global
        self.progress_label_total = Gtk.Label(halign=Gtk.Align.START)
        grid.attach(self.progress_label_total, 0, 2, 6, 1)

        # Progresso da conversão do arquivo
        self.progress_bar_arquivo = Gtk.ProgressBar(show_text=True)
        grid.attach(self.progress_bar_arquivo, 0, 3, 6, 1)

        # Titulo do arquivo
        self.progress_label_arquivo = Gtk.Label(halign=Gtk.Align.START)
        grid.attach(self.progress_label_arquivo, 0, 4, 6, 1)

        self.get_content_area().pack_start(grid, True, True, 0)
        self.show_all()

        thread = Thread(target=self.processa_videos)
        thread.daemon = True
        thread.start()

    def update_progess(self, titulo_barra_total, titulo_label_total, titulo_label_atual, progresso_arquivo, progresso_total):
        # Atualiza os contadores do arquivo atual e progresso total
        self.progress_bar_total.set_text(titulo_barra_total)
        self.progress_label_total.set_text(titulo_label_total)
        self.progress_label_arquivo.set_text(titulo_label_atual)

        # Atualiza o progress bar da conversão do arquivo
        self.progress_bar_arquivo.set_fraction(progresso_arquivo)  # O processo deve ser entre 0.0 e 1.0
        self.progress_bar_total.set_fraction(progresso_total)  # O processo deve ser entre 0.0 e 1.0

        return False

    def processa_videos(self):
        # Constante com os textos exibidos pelo ffmpeg
        DURATION = "Duration:"
        FRAME = "frame="
        TIME = "time="
        NA = "N/A"
        ultimaLinha = None

        global processo_ffmpeg
                 
        for arquivo in self.lista_arquivos:
            try:
                if not os.path.isfile(arquivo) and self.arquivoDestino is None:
                    debug("Ignorando aquivo inexistente: " + arquivo)
                    self.failed = True
                    continue

                # Extrai a extensão do video
                nome = os.path.basename(arquivo)
                extensao = nome[nome.rfind(".") + 1:]

                # Utilizar a extensão apenas se o sufixo não foi especificado
                if self.sufixoArquivo is None:
                    sufixoArquivo = extensao
                else:
                    sufixoArquivo = self.sufixoArquivo
                
                # Cria o nome do arquivo de destino
                novo_arquivo = self.dir_destino + os.sep + nome[:nome.rfind(".")] + sufixoArquivo
                novo_arquivo = novo_arquivo.replace("${EXTENSAO}", extensao)
                if self.arquivoDestino is not None:
                    novo_arquivo = self.arquivoDestino

                # Monta os parâmetros do ffmpeg
                args = [get_caminho_ffmpeg(), "-hide_banner"]
                args.extend(self.params)

                # Substitui as variáveis nos parâmetros
                for idx, val in enumerate(args):  # @UnusedVariable
                    args[idx] = args[idx].replace("${ORIGEM}", arquivo)
                    args[idx] = args[idx].replace("${DESTINO}", novo_arquivo)
                    args[idx] = args[idx].replace("${EXTENSAO}", extensao)

                # Cria o diretório, se não existir
                directory = os.path.dirname(novo_arquivo)
                if not os.path.exists(directory):
                    debug("Criando o diretório " + directory)
                    os.makedirs(directory)

                # Verifica se o vídeo de destino existe
                if os.path.isfile(novo_arquivo):
                    debug("Removendo arquivo de destino existente: " + novo_arquivo)
                    os.remove(novo_arquivo)

                max_secs = 0
                cur_secs = 0

                # Checa se o usuário interrrompeu a conversão
                if self.must_stop:
                    return None

                # Efetua a conversão do arquivo de video
                debug("Executando aplicação: " + ' '.join(args))

                processo_ffmpeg = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)

                # Inicia o processo e itera entre as linhas recebidas no stdout
                for line in iter(processo_ffmpeg.stdout.readline, ''):
                    ultimaLinha = line
                    if DURATION in line:
                        # Essa linha contém o tamanho total do vídeo
                        try:
                            if NA in line:
                                max_secs = self.segundosTotal
                            else:
                                tmp = line[line.find(DURATION):]
                                tmp = tmp[tmp.find(" ") + 1:]
                                tmp = tmp[0: tmp.find(".")]
                                x = time.strptime(tmp, '%H:%M:%S')
                                max_secs = datetime.timedelta(hours=x.tm_hour, minutes=x.tm_min, seconds=x.tm_sec).total_seconds()

                            # Estatísticas da conversão total
                            titulo_barra_total = "[" + seconds_to_time(self.segundosConcluidos) + " / " + seconds_to_time(self.segundosTotal) + "]"
                            
                            titulo_label_total = "Original: " + os.path.basename(arquivo) + " - " + seconds_to_time(max_secs)
                            if os.path.isfile(novo_arquivo):
                                titulo_label_total = titulo_label_total + " (" + human_size(os.stat(arquivo).st_size) + ")"
                                
                            progresso_total = (self.segundosConcluidos + cur_secs) / self.segundosTotal  # Percentual do progresso
                            progresso_arquivo = cur_secs / max_secs

                            titulo_label_atual = "Destino: " + os.path.basename(novo_arquivo) + " - " + seconds_to_time(cur_secs)
                            if os.path.isfile(novo_arquivo):
                                titulo_label_atual = titulo_label_atual + " (" + human_size(os.stat(novo_arquivo).st_size) + ")"
                                
                            # Atualiza as estatíticas do total e o nome do arquivo de destino
                            GLib.idle_add(self.update_progess, titulo_barra_total, titulo_label_total, titulo_label_atual, progresso_arquivo, progresso_total)

                        except ValueError:
                            debug("Falha ao converter o horário: " + tmp)
    
                    elif line.startswith(FRAME) and TIME in line:
                        try:
                            # Captura o tempo da conversão (timestamp)
                            tmp = line[line.find(TIME):]
                            tmp = tmp[tmp.find("=") + 1: tmp.find(".")]
                            x = time.strptime(tmp, '%H:%M:%S')
                            cur_secs = datetime.timedelta(hours=x.tm_hour, minutes=x.tm_min, seconds=x.tm_sec).total_seconds()
                        except ValueError:
                            debug("Falha ao converter o horário: " + tmp)

                    # Atualiza o progresso da conversão do arquivo de destino
                    if cur_secs > 0 and max_secs > 0:
                        progresso_total = (self.segundosConcluidos + cur_secs) / self.segundosTotal  # Percentual do progresso
                        progresso_arquivo = cur_secs / max_secs
                        titulo_barra_total = "[" + seconds_to_time(self.segundosConcluidos + cur_secs) + " / " + seconds_to_time(self.segundosTotal) + "]"
                        
                        if os.path.isfile(novo_arquivo):
                            titulo_label_atual = "Destino: " + os.path.basename(novo_arquivo) + " - " + seconds_to_time(cur_secs) + " (" + human_size(os.stat(novo_arquivo).st_size) + ")"
                        GLib.idle_add(self.update_progess, titulo_barra_total, titulo_label_total, titulo_label_atual, progresso_arquivo, progresso_total)

                # Ao final do arquivo, incrementa o tempo ao tempo de concluídos
                self.segundosConcluidos = self.segundosConcluidos + cur_secs
                
                # Finaliza o processo do ffmpeg
                processo_ffmpeg.stdout.close()
                exitCode = processo_ffmpeg.wait()
                # Verifica o error code do processo
                self.failed = self.failed or exitCode != 0 
                if self.failed:
                    debug("Mensagem de erro: " + ultimaLinha) 

                if os.path.isfile(arquivo):
                    debug("Vídeo original: " + arquivo + " (" + human_size(os.stat(arquivo).st_size) + ")")

                if os.path.isfile(novo_arquivo):
                    debug("Vídeo processado: " + novo_arquivo + " (" + human_size(os.stat(novo_arquivo).st_size) + ")")

            except Exception as e:
                debug("Falha ao processar o arquivo de vídeo " + arquivo + " : " + str(e))
                self.failed = True

        self.close()


class ExtrairDialog(Gtk.Dialog):
    entry_start = None
    entry_end = None
    endPosition = None

    def __init__(self, parent, startPosition, endPosition):
        Gtk.Dialog.__init__(self, "Seção a ser extraída do vídeo", parent, 0,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                             Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(350, 150)
        self.set_border_width(10)

        self.endPosition = endPosition

        debug("Solicitação de informação de extração do video ao usuário.")

        topBox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Inicio
        box = Gtk.Box()
        box.pack_start(Gtk.Label(label="Tempo inicial para extração:", halign=Gtk.Align.START), True, True, 6)
        self.entry_start = Gtk.Entry()
        self.entry_start.set_text(startPosition)
        box.pack_end(self.entry_start, True, True, 0)
        topBox.pack_start(box, True, True, 0)

        # Fim
        box = Gtk.Box()
        box.pack_start(Gtk.Label(label="Tempo final para extração:", halign=Gtk.Align.START), True, True, 6)
        self.entry_end = Gtk.Entry()
        self.entry_end.set_text(endPosition)
        box.pack_end(self.entry_end, True, True, 0)
        topBox.pack_start(box, True, True, 0)

        self.get_content_area().pack_start(topBox, True, True, 0)
        self.show_all()

    def do_valida_campos(self):
        start = self.entry_start.get_text().strip()
        end = self.entry_end.get_text().strip()

        pattern = "[0-9]{2}:[0-9]{2}:[0-9]{2}"

        if re.search(pattern, start) is None:
            return show_message('Formato de data inválido:', 'Informe o tempo inicial no formato hh:mm:ss.')

        if re.search(pattern, end) is None:
            return show_message('Formato de data inválido:', 'Informe o tempo final no formato hh:mm:ss.')

        if time_to_seconds(start) >= time_to_seconds(end):
            return show_message('Valores inválidos:', 'O tempo final deve ser maior do que o tempo inicial.')

        if time_to_seconds(start) >= time_to_seconds(self.endPosition) or time_to_seconds(end) >= time_to_seconds(self.endPosition):
            return show_message('Valores inválidos:', "Os valores devem ser menor do que " + self.endPosition)

        return Gtk.ResponseType.OK

    def show_and_get_info(self):
        while self.run() == Gtk.ResponseType.OK:
            if self.do_valida_campos() is not None:
                resp = {"inicio":self.entry_start.get_text().strip(), "fim":self.entry_end.get_text().strip()}
                self.destroy()
                return resp

        self.destroy()
        return None


class CropDialog(Gtk.Dialog):
    spinX = None
    spinY = None
    spinW = None
    spinH = None
    width = 0
    height = 0

    def __init__(self, parent, width, height):
        Gtk.Dialog.__init__(self, "Região a ser extraída do vídeo", parent, 0,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                             Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(350, 150)
        self.set_border_width(10)

        self.width = width
        self.height = height

        debug("Solicitação de informação de extração do video ao usuário.")

        topBox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Posição inicial Vertical
        box = Gtk.Box()
        box.pack_start(Gtk.Label(label="Posição inicial Vertical:", halign=Gtk.Align.START), True, True, 6)
        adjustmentX = Gtk.Adjustment(0, 0, height, 10, 100, 0)
        self.spinX = Gtk.SpinButton()
        self.spinX.set_adjustment(adjustmentX)
        self.spinX.set_numeric(True)
        box.pack_end(self.spinX, True, True, 0)
        topBox.pack_start(box, True, True, 0)

        # Posição inicial Horizontal
        box = Gtk.Box()
        box.pack_start(Gtk.Label(label="Posição inicial Horizontal:", halign=Gtk.Align.START), True, True, 6)
        adjustmentY = Gtk.Adjustment(0, 0, width, 10, 100, 0)
        self.spinY = Gtk.SpinButton()
        self.spinY.set_adjustment(adjustmentY)
        self.spinY.set_numeric(True)
        box.pack_end(self.spinY, True, True, 0)
        topBox.pack_start(box, True, True, 0)

        # Largura
        box = Gtk.Box()
        box.pack_start(Gtk.Label(label="Largura:", halign=Gtk.Align.START), True, True, 6)
        adjustmentW = Gtk.Adjustment(width, 1, width, 10, 100, 0)
        self.spinW = Gtk.SpinButton()
        self.spinW.set_adjustment(adjustmentW)
        self.spinW.set_numeric(True)
        box.pack_end(self.spinW, True, True, 0)
        topBox.pack_start(box, True, True, 0)

        # Altura
        box = Gtk.Box()
        box.pack_start(Gtk.Label(label="Altura:", halign=Gtk.Align.START), True, True, 6)
        adjustmentH = Gtk.Adjustment(height, 1, height, 10, 100, 0)
        self.spinH = Gtk.SpinButton()
        self.spinH.set_adjustment(adjustmentH)
        self.spinH.set_numeric(True)
        box.pack_end(self.spinH, True, True, 0)
        topBox.pack_start(box, True, True, 0)

        self.get_content_area().pack_start(topBox, True, True, 0)
        self.show_all()

    def show_and_get_info(self):
        while self.run() == Gtk.ResponseType.OK:
            resp = {"x":self.spinX.get_value() , "y":self.spinY.get_value(), "w":self.spinW.get_value(), "h":self.spinH.get_value()}
            self.destroy()
            return resp

        self.destroy()
        return None


class DeshakeDialog(Gtk.Dialog):
    spinX = None
    spin_zoom = None

    def __init__(self, parent):
        Gtk.Dialog.__init__(self, "Estabilização de vídeos", parent, 0,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                             Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(350, 150)
        self.set_border_width(10)

        debug("Solicitação de informação sobre a estabilização do video.")

        topBox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Intensidade
        box = Gtk.Box()
        box.pack_start(Gtk.Label(label="Intensidade do movimento:", halign=Gtk.Align.START), True, True, 6)

        adjustment_intensity = Gtk.Adjustment(0, 0, 10, 1, 10, 0)
        self.spinX = Gtk.SpinButton()
        self.spinX.set_adjustment(adjustment_intensity)
        self.spinX.set_numeric(True)
        self.spinX.set_value(3)

        box.pack_end(self.spinX, True, True, 0)
        topBox.pack_start(box, True, True, 0)

        # Zoom
        box = Gtk.Box()
        box.pack_start(Gtk.Label(label="Zoom na imagem (pixeis):", halign=Gtk.Align.START), True, True, 6)

        adjustment_zoom = Gtk.Adjustment(0, 0, 10, 1, 10, 0)
        self.spin_zoom = Gtk.SpinButton()
        self.spin_zoom.set_adjustment(adjustment_zoom)
        self.spin_zoom.set_numeric(True)
        self.spin_zoom.set_value(6)

        box.pack_end(self.spin_zoom, True, True, 0)
        topBox.pack_end(box, True, True, 0)

        self.get_content_area().pack_start(topBox, True, True, 0)
        self.show_all()

    def do_valida_campos(self):

        if self.spinX.get_value_as_int() < 1:
            return show_message('Campo obrigatório não informado:', 'É necessário informar a intensidade da agitação (0-10).')

        if self.spin_zoom.get_value_as_int() < 1:
            return show_message('Campo obrigatório não informado:', 'É necessário informar o tamanho do zoom em píxeis na imagem.')

        return Gtk.ResponseType.OK

    def show_and_get_info(self):
        while self.run() == Gtk.ResponseType.OK:
            if self.do_valida_campos() is not None:
                resp = {"intensity":self.spinX.get_value_as_int(), "zoom":self.spin_zoom.get_value_as_int()}
                self.destroy()
                return resp

        self.destroy()
        return None


class InputDialog(Gtk.Dialog):
    # Dialog de solicitação de dados em um campo de texto ou combo
    text_entry = None
    combo_codec = None

    def __init__(self, parent, message, default, opcoes):
        Gtk.Dialog.__init__(self, "Solicitação de informação do usuário", parent, 0,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                             Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(350, 150)
        self.set_border_width(10)

        topbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        topbox.pack_start(Gtk.Label(label=message, halign=Gtk.Align.START), True, True, 0)

        debug("Solicitação de informção ao usuário: " + message)
        if opcoes is None:
            # Campo de texto
            self.text_entry = Gtk.Entry()
            self.text_entry.set_text(default)
            topbox.pack_start(self.text_entry, True, True, 0)
        else:
            self.combo_codec = Gtk.ComboBoxText()
            # Campo de texto
            for i, word in enumerate(opcoes.split('|')):
                self.combo_codec.append_text(word)
                if default and word == default:
                    self.combo_codec.set_active(i)

            topbox.pack_start(self.combo_codec, True, True, 0)

        self.get_content_area().pack_start(topbox, False, False, 0)
        self.show_all()

    def do_valida_campos(self):
        if self.text_entry is not None and not self.text_entry.get_text().strip():
            return show_message('Campo obrigatório não informado:', 'É necessário especificar o valor do campo.')

        if self.combo_codec is not None and not self.combo_codec.get_active_text():
            return show_message('Campo obrigatório não informado:', 'É necessário selecionar um item.')

        return Gtk.ResponseType.OK

    def show_and_get_info(self):
        while self.run() == Gtk.ResponseType.OK:
            if self.do_valida_campos() is not None:
                if self.text_entry is not None:
                    resp = self.text_entry.get_text().strip()
                else:
                    resp = self.combo_codec.get_active_text()
                self.destroy()
                return resp

        self.destroy()
        return None


class ConcatenarDialog(Gtk.Dialog):
    # Dialogo para exibição do log

    def __init__(self, parent, arquivos, destino):
        Gtk.Dialog.__init__(self, "Arquivos a serem concatenados", parent, 0,
                             (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                             Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(600, 480)
        self.set_border_width(10)

        # Lista com os arquivos

        self.textview = Gtk.TextView()

        scrolledwindow = Gtk.ScrolledWindow()
        scrolledwindow.set_hexpand(True)
        scrolledwindow.set_vexpand(True)
        scrolledwindow.add(self.textview)

        self.grid = Gtk.Grid()
        self.grid.attach(scrolledwindow, 0, 0, 6, 6)

        # Carrega a lista de arquivos
        tmp = ""
        for arquivo in arquivos:
            tmp = tmp + "file " + arquivo + "\n"

        self.textview.get_buffer().set_text(tmp)

        # Codec de destino
        flowbox = Gtk.FlowBox()       
        flowbox.add(Gtk.Label(label="Codec do novo arquivo:", halign=Gtk.Align.START))
        
        self.combo_codec = Gtk.ComboBoxText()
        for codec in CODECS_VIDEO:
            self.combo_codec.append_text(codec)
        self.combo_codec.set_active(0)
        flowbox.add(self.combo_codec)

        self.grid.attach(flowbox, 0, 7, 3, 1)
               
        # Arquivo de destino
        box = Gtk.Box()
        box.pack_start(Gtk.Label(label="Arquivo a ser gerado:", halign=Gtk.Align.START), False, False, 4)
        self.text_entry = Gtk.Entry()
        self.text_entry.set_text(destino + os.sep + "videos_concatenados.mp4")
        box.pack_end(self.text_entry, True, True, 4)

        self.grid.attach(box, 0, 8, 6, 1)

        self.get_content_area().pack_start(self.grid, True, True, 0)

        self.show_all()

    def show_and_get_info(self):

        while self.run() == Gtk.ResponseType.OK:
            if self.text_entry.get_text() is not None:

                buf = self.textview.get_buffer()
                text = buf.get_text(buf.get_start_iter(),
                        buf.get_end_iter(),
                        True)
                open(ARQUIVO_VIDEOS_CONCATENA, 'w').write(text)

                resp = {"destino":self.text_entry.get_text(), "codec":self.combo_codec.get_active_text()}
                self.destroy()

                return resp

        self.destroy()
        return None


class LogViewerDialog(Gtk.Dialog):
    # Dialogo para exibição do log

    def __init__(self, parent):
        Gtk.Dialog.__init__(self, "Log da aplicação", parent, 0, (Gtk.STOCK_OK, Gtk.ResponseType.OK))

        self.set_size_request(1024, 600)
        self.set_border_width(10)

        scrolledwindow = Gtk.ScrolledWindow()
        scrolledwindow.set_hexpand(True)
        scrolledwindow.set_vexpand(True)

        self.grid = Gtk.Grid()
        self.grid.attach(scrolledwindow, 0, 1, 3, 1)

        self.textview = Gtk.TextView()
        scrolledwindow.add(self.textview)

        # Carrega o arquivo de log
        self.textview.get_buffer().set_text(open(ARQUIVO_LOG).read())

        self.get_content_area().pack_start(self.grid, True, True, 0)
        self.show_all()

    def show_and_get_info(self):
        self.run()
        self.destroy()
        return None


class MainWindow(Gtk.Window):
    colunas = ["Processar", "Arquivo", "Tamanho", "Detalhes"]
    buttons = []
    popup_menu = Gtk.Menu()

    def __init__(self):
        Gtk.Window.__init__(self, title="Video Tools - " + versao_aplicacao)

        self.set_icon_name("application-x-executable")
        Gtk.Settings().set_property('gtk_button_images', True)

        # Clipboar para cópia do texto
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

        self.set_resizable(True)
        self.set_border_width(10)

        # Container principal
        grid = Gtk.Grid()
        grid.set_column_homogeneous(True)
        grid.set_row_homogeneous(True)
        grid.set_column_spacing(4)
        grid.set_row_spacing(6)

        # Campo Origem

        self.edit_origem = Gtk.Entry()
        self.edit_origem.set_activates_default(True)
        self.edit_origem.set_text(get_app_settings("dir_origem"))

        button = Gtk.Button.new_from_icon_name("folder-open", Gtk.IconSize.BUTTON)
        button.connect("clicked", self.do_click_origem)

        box = Gtk.Box()
        box.pack_start(Gtk.Label(label="Diretório de Origem:", halign=Gtk.Align.START), False, False, 0)
        box.pack_start(self.edit_origem, True, True, 4)
        box.pack_end(button, False, False, 0)

        grid.attach(box, 0, 0, 6, 1)

        # Ler aquivos
        self.button_ler_arquivos = self.create_icon_and_label_button("Atualizar", "reload", False)
        self.button_ler_arquivos.connect("clicked", self.do_load_file_list)
        grid.attach(self.button_ler_arquivos, 6, 1, 1, 1)

        # Converter
        self.button_convert = self.create_icon_and_label_button("Converter", "add-folder-to-archive", True)
        self.button_convert.connect("clicked", self.do_video_convert)
        grid.attach(self.button_convert, 6, 3, 1, 1)

        # Redimensionar
        self.button_resize = self.create_icon_and_label_button("Redimensionar", "zoom-in", True)
        self.button_resize.connect("clicked", self.do_video_resize)
        grid.attach(self.button_resize, 6, 4, 1, 1)

        # Rotacionar
        self.button_rotate = self.create_icon_and_label_button("Rotacionar", "rotate", True)
        self.button_rotate.connect("clicked", self.do_video_rotate)
        grid.attach(self.button_rotate, 6, 5, 1, 1)

        # Extrair intervalo
        self.button_extract_interval = self.create_icon_and_label_button("Extrair intervalo", "document-export", True)
        self.button_extract_interval.connect("clicked", self.do_video_extract_interval)
        grid.attach(self.button_extract_interval, 6, 6, 1, 1)

        # Extrair seção
        self.button_extract_section = self.create_icon_and_label_button("Extrair Região", "gtk-leave-fullscreen", True)
        self.button_extract_section.connect("clicked", self.do_video_extract_region)
        grid.attach(self.button_extract_section, 6, 7, 1, 1)

        # Concatenar
        self.button_concatenate = self.create_icon_and_label_button("Concatenar", "object-flip-horizontal", True)
        self.button_concatenate.connect("clicked", self.do_video_concatenate)
        grid.attach(self.button_concatenate, 6, 8, 1, 1)

        # Estabilizar
        if "--enable-libvidstab" in get_ffmpeg_features():
            self.button_deshake = self.create_icon_and_label_button("Estabilizar", "media-playlist-shuffle", True)
            self.button_deshake.connect("clicked", self.do_video_deshake)
            grid.attach(self.button_deshake, 6, 9, 1, 1)

        # Logs
        button = self.create_icon_and_label_button("Logs", "system-search", False)
        button.connect("clicked", self.do_click_logs)
        grid.attach(button, 6, 11, 1, 1)

        # Sair
        button = self.create_icon_and_label_button("Fechar", "window-close", False)
        button.connect("clicked", self.do_click_close)
        grid.attach(button, 6, 12, 1, 1)

        # grid de arquivos

        # Cria o grid
        self.store = Gtk.ListStore(bool, str, str, str)

        self.filtro = self.store.filter_new()
        # self.filtro.set_visible_func(self.do_filter_grid)
        cellRenderer = Gtk.CellRendererText()

        # Adiciona as colunas ao TreeView
        self.treeview = Gtk.TreeView(model=self.store)
        self.treeview.connect("button_press_event", self.do_show_popup)

        # Colunas 0 e 1 não são texto
        col1 = Gtk.TreeViewColumn("Processar", Gtk.CellRendererToggle(), active=0)
        col1.set_sort_column_id(0)
        self.treeview.append_column(col1)

        # Adiciona as demais colunas
        for i, column_title in enumerate(self.colunas):
            column = Gtk.TreeViewColumn(column_title, cellRenderer, text=i)
            if i > 0:  # Coluna 0 foi adicionada manualmente
                self.treeview.append_column(column)
            self.store.set_sort_func(i, compare, None)
            column.set_sort_column_id(i)

        self.treeview.connect("row-activated", self.on_tree_double_clicked)

        # Adiciona o treeview a um scrollwindow
        scrollable_treelist = Gtk.ScrolledWindow()
        scrollable_treelist.set_vexpand(True)
        scrollable_treelist.add(self.treeview)
        grid.attach(scrollable_treelist, 0, 1, 6, 12)

        # Label de seleção dos arquivos
        self.label_status_copia = Gtk.Label(label="", halign=Gtk.Align.START)
        grid.attach(self.label_status_copia, 0, 13, 7, 1)

        self.add(grid)
        self.do_atualiza_contador_selecao()
        
        i1 = Gtk.MenuItem("Marcar todos os videos")
        i1.connect("activate", self.do_marca_todos)
        self.popup_menu.append(i1)
        i2 = Gtk.MenuItem("Desmarcar todos os videos")
        i2.connect("activate", self.do_desmarca_todos)
        self.popup_menu.append(i2)
        i3 = Gtk.MenuItem("Marcar videos não H265")
        i3.connect("activate", self.do_marcar_nao_h265)
        self.popup_menu.append(i3)
        i4 = Gtk.MenuItem("Apagar videos marcados")
        i4.connect("activate", self.do_apagar_selecionados)
        self.popup_menu.append(i4)
                  
        self.popup_menu.show_all()

    def do_show_popup(self, tv, event):  # @UnusedVariable
        if event.button == 3:
            self.popup_menu.popup(None, None, None, None, 0, Gtk.get_current_event_time())

    def do_apagar_selecionados(self, widget):  # @UnusedVariable
        debug("MenuItem: Apagar videos marcados")
        arquivos = self.listar_arquivos_selecionados()
        if len(arquivos) >0:
            dialog = Gtk.MessageDialog(self, 0, Gtk.MessageType.QUESTION,Gtk.ButtonsType.YES_NO, "Confirmação da exclusão")
            dialog.format_secondary_text("Você realmente deseja remover os "+str(len(arquivos))+" arquivos marcados?")
            response = dialog.run()
            if response == Gtk.ResponseType.YES:
                for arquivo in arquivos:
                    debug("Removendo arquivo "+arquivo)
                    os.remove(arquivo)
                dialog.destroy()
            
        self.do_load_file_list(widget)
    
    def do_marcar_nao_h265(self, widget):  # @UnusedVariable
        debug("MenuItem: Marcar videos não H265")
        for row in self.store:
            if 'hevc' not in row[3]: 
                row[0] = True

        self.do_atualiza_contador_selecao()

    def do_marca_todos(self, widget):  # @UnusedVariable
        debug("MenuItem: Marcar todos os videos")
        for row in self.store:
            row[0] = True

        self.do_atualiza_contador_selecao()

    def do_desmarca_todos(self, widget):  # @UnusedVariable
        debug("MenuItem: Desmarcar todos os videos")
        for row in self.store:
            row[0] = False

        self.do_atualiza_contador_selecao()
        
    def do_click_origem(self, widget):  # @UnusedVariable
        debug("Selecionando diretório de origem")

        editor = self.edit_origem

        dialog = Gtk.FileChooserDialog("Selecione o diretório de origem", self, Gtk.FileChooserAction.SELECT_FOLDER,
                                       (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))

        currentDir = editor.get_text().strip()
        if os.path.isdir(currentDir):
            dialog.set_current_folder(currentDir)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            editor.set_text(dialog.get_filename())
            debug("Diretório de origem selecionado: " + dialog.get_filename())
            set_app_settings("dir_origem", dialog.get_filename())

        dialog.destroy()

    def do_video_convert(self, widget):  # @UnusedVariable
        nome_codec = InputDialog(win, 'Selecione o novo formato do video', VIDEO_H265, '|'.join(CODECS_VIDEO) + "|" + '|'.join(CODECS_AUDIO)).show_and_get_info()
        if nome_codec is not None:
            codec = get_codec_info(nome_codec)
            sufixoArquivo = codec["sufixo"]

            params = ["-i", "${ORIGEM}"]
            params.extend(codec["params"])
            params.append("${DESTINO}")
            
            arquivos = self.listar_arquivos_selecionados()
            segundosTotal = self.obter_total_segundos()

            self.executa_ffmpeg("Conversão dos videos para o formato " + nome_codec, params, arquivos, segundosTotal, sufixoArquivo, None, True)
   
    def do_video_concatenate(self, widget):  # @UnusedVariable

        # Remove o arquivo temporário da lista de arquivos
        if os.path.isfile(ARQUIVO_VIDEOS_CONCATENA):
            os.remove(ARQUIVO_VIDEOS_CONCATENA)

        info = ConcatenarDialog(win, self.listar_arquivos_selecionados(), self.edit_origem.get_text()).show_and_get_info()
        if info is not None:
            aquivoDestino = info["destino"]
            codec = get_codec_info(info["codec"])

            params = ["-f", "concat", "-safe", "0", "-i", ARQUIVO_VIDEOS_CONCATENA]
            params.extend(codec["params"])
            params.append("${DESTINO}")
        
            print(str(params))
            segundosTotal = self.obter_total_segundos()
            self.executa_ffmpeg("Concatenação de vídeos", params, None, segundosTotal, None, aquivoDestino, True)

        # Remove o arquivo temporário da lista de arquivos
        if os.path.isfile(ARQUIVO_VIDEOS_CONCATENA):
            os.remove(ARQUIVO_VIDEOS_CONCATENA)

    def do_video_extract_interval(self, widget):  # @UnusedVariable
        arquivos = self.listar_arquivos_selecionados()

        if len(arquivos) is not 1:
            return show_message("Falha na seleção de arquivos", "Essa operação só é permitida para um arquivo por vez.")

        # Localiza o tamanho total do video selecionado
        for row in self.store:
            if row[0]:
                endPosition = row[3][10:18]

        info = ExtrairDialog(win, "00:00:00", endPosition).show_and_get_info()
        if info is not None:
            ini = info["inicio"]
            fim = info["fim"]

            temp = seconds_to_time(time_to_seconds(fim) - time_to_seconds(ini))

            params = ["-i", "${ORIGEM}", "-ss", ini, "-t", temp, "-strict", "-2", "${DESTINO}"]

            arquivos = self.listar_arquivos_selecionados()
            segundosTotal = self.obter_total_segundos()

            self.executa_ffmpeg("Extrair um intervalo do vídeo", params, arquivos, segundosTotal, "_section.${EXTENSAO}", None, True)

    def do_video_extract_region(self, widget):  # @UnusedVariable
        arquivos = self.listar_arquivos_selecionados()

        if len(arquivos) is not 1:
            return show_message("Falha na seleção de arquivos", "Essa operação só é permitida para um arquivo por vez.")

        width = 1280
        height = 720

        # Localiza a resolução do video selecionado
        for row in self.store:
            if row[0]:
                m = re.search("([0-9]{2,}x[0-9]{2,})", row[3])
                if m is not None:
                    temp = m.group(0)
                    width = temp[:temp.find("x")]
                    height = temp[temp.find("x") + 1:]
                    break

        info = CropDialog(win, int(width), int(height)).show_and_get_info()
        if info is not None:

            params = ["-i", "${ORIGEM}", "-vf", "crop=" + str(info["w"]) + ":" + str(info["h"]) + ":" + str(info["x"]) + ":" + str(info["y"]), "-strict", "-2", "${DESTINO}"]

            arquivos = self.listar_arquivos_selecionados()
            segundosTotal = self.obter_total_segundos()

            self.executa_ffmpeg("Extraindo a região do vídeo", params, arquivos, segundosTotal, "_cropped.${EXTENSAO}", None, True)

    def do_video_deshake(self, widget):  # @UnusedVariable
        info = DeshakeDialog(win).show_and_get_info()
        if info is not None:
            intensity = info["intensity"]
            zoom = info["zoom"]

            vetores = self.edit_origem.get_text() + os.sep + "transform_vectors.trf"

            arquivos = self.listar_arquivos_selecionados()
            segundosTotal = self.obter_total_segundos()

            # Step 1. Calculating the stabilization vectors.
            params = ["-i", "${ORIGEM}", "-vf", "vidstabdetect=stepsize=6:shakiness=" + str(intensity) + ":result=" + vetores, "-f", "null", "-"]
            self.executa_ffmpeg("Calculando vetores de estabilização", params, arquivos, segundosTotal, None , None, False)

            # Step 2. Transcoding the video with the data from Step 1 into a nice and smooth output video file.
            params = ["-i", "${ORIGEM}", "-vf", "vidstabtransform=input=" + vetores + ":zoom=" + str(zoom) + ":smoothing=30,unsharp=5:5:0.8:3:3:0.4", "-strict", "-2", "${DESTINO}"]
            self.executa_ffmpeg("Estabilizando o video", params, arquivos, segundosTotal, "_stab.${EXTENSAO}" , None, True)

    def do_video_resize(self, widget):  # @UnusedVariable
        width = 1280
        height = 720

        # Localiza o tamanho total do video selecionado
        for row in self.store:
            if row[0]:
                m = re.search("([0-9]{2,}x[0-9]{2,})", row[3])
                if m is not None:
                    temp = m.group(0)
                    width = temp[:temp.find("x")]
                    height = temp[temp.find("x") + 1:]
                    break

        info = InputDialog(win, 'Informe a nova resolução do vídeo', str(width) + "x" + str(height), None).show_and_get_info()
        if info is not None:
            m = re.search("([0-9]{2,}x[0-9]{2,})", info)
            if m is None:
                return show_message("Resolução inválida", "É necessário informar uma resolução no formato 800x600.")

            width = info[:info.find("x")]
            height = info[info.find("x") + 1:]

            params = ["-i", "${ORIGEM}", "-vf", "scale=w=" + width + ":h=" + height + "", "-q:a", "0", "-q:v", "0", "-strict", "-2", "${DESTINO}"]

            arquivos = self.listar_arquivos_selecionados()
            segundosTotal = self.obter_total_segundos()

            self.executa_ffmpeg("Recortar uma região do vídeo", params, arquivos, segundosTotal, "_resized.${EXTENSAO}", None, True)

    def do_video_rotate(self, widget):  # @UnusedVariable

        opcoes = ["90 Graus sentido horário", "90 Graus sentido anti-horário", "180 Graus", "90 Graus sentido anti-horário com flip vertical", "90 Graus sentido horário com flip vertical", "Flip horizontal", "Flip vertical"]
        filtro = ["transpose=1", "transpose=2", "transpose=2,transpose=2", "transpose=0", "transpose=3", "hflip", "vflip"]

        info = InputDialog(win, 'Informe a rotação que será aplicada aos vídeos', opcoes[0], "|".join(opcoes)).show_and_get_info()
        if info is not None:
            for idx, item in enumerate(opcoes):
                if item == info:
                    params = ["-i", "${ORIGEM}", "-vf", filtro[idx], "-q:a", "0", "-q:v", "0", "-strict", "-2", "${DESTINO}"]

            arquivos = self.listar_arquivos_selecionados()
            segundosTotal = self.obter_total_segundos()
    
            self.executa_ffmpeg("Rotacionando o arquivo de vídeo", params, arquivos, segundosTotal, "_rotated.${EXTENSAO}", None, True)

    def do_load_file_list(self, widget):  # @UnusedVariable
        global arquivos_origem
        global origem_pronto
        # Monta a lista de arquivos
        arquivos_origem = [y for x in os.walk(self.edit_origem.get_text()) for y in glob(os.path.join(x[0], '*.*'))]
        tamanho = 0
        for arquivo in arquivos_origem:
            tamanho = tamanho + os.stat(arquivo).st_size  # in bytes

        debug("Arquivos no diretório de origem: " + str(len(arquivos_origem)) + " (" + human_size(tamanho) + ")")
        debug("Consulta da lista de arquivos de origem concluída, populando a grid de arquivos")

        self.store.clear()
        posSrc = len(self.edit_origem.get_text()) + 1
        for arquivo in arquivos_origem:

            if self.is_video(arquivo) and os.stat(arquivo).st_size > 0:
                detalhe = self.get_file_info(arquivo)
                if detalhe:
                    processar = False
                    tamanho = human_size(os.stat(arquivo).st_size)
                    arquivoAbr = arquivo[posSrc:]
    
                    self.store.insert(0, [
                        processar ,
                        arquivoAbr,
                        tamanho,
                        detalhe
                    ])

        # Atualiza o contador
        self.do_atualiza_contador_selecao()
        debug("Grid de arquivos populada")

    def get_file_info(self, arquivo):
        pattern = re.compile("(Duration: [0-9]{2,}:[0-9]{2,}:[0-9]{2,})|(Video: [^\s]+)|([0-9]{2,}x[0-9]{2,})|([0-9|.]+ fps)|(Audio: [^\s]+)|([0-9]+ Hz)")
        args = [get_caminho_ffmpeg(), "-hide_banner", "-i", arquivo]

        global processo_ffmpeg
        processo_ffmpeg = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)

        lines = ""
        # Inicia o processo e concatena as linhas do output
        for line in iter(processo_ffmpeg.stdout.readline, ''):
            
            # Considera apenas as linhas essenciais
            if line.find("Stream #0") or line.find(" Duration:"):
                lines = lines + line

        # Recupera o texto dos grupos da regex
        resp = ""
        for m in pattern.finditer(lines):
            resp = resp + m.group() + " "

        # Finaliza o processo do ffmpeg
        processo_ffmpeg.stdout.close()
        processo_ffmpeg.wait()

        return resp

    def do_atualiza_contador_selecao(self):
        cont = 0
        size = 0
        secs = 0

        for row in self.store:
            if row[0]:
                arquivo = self.edit_origem.get_text() + os.sep + row[1]
                time = row[3][10:18]

                if self.is_video(arquivo):
                    cont += 1
                    size += os.stat(arquivo).st_size
                    secs = secs + time_to_seconds(time)

        self.label_status_copia.set_text("Arquivos selecionados: " + str(cont) + " / " + str(len(self.store)) + " (" + human_size(size) + ") - " + seconds_to_time(secs))

        # Habilita os botões
        for botao in self.buttons:
            botao.set_sensitive(cont > 0)

        self.button_extract_interval.set_sensitive(cont == 1)
        self.button_extract_section.set_sensitive(cont == 1)
        self.button_concatenate.set_sensitive(cont > 1)

    def is_video(self, arquivo):
        for ext in get_app_settings("extensoes_video").split('|'):
            if arquivo.lower().endswith(ext.lower()):
                return True
        return False

    def listar_arquivos_selecionados(self):
        arquivos = []
        for row in self.store:
            if row[0]:
                arquivos.append(self.edit_origem.get_text() + os.sep + row[1])
        return arquivos
    
    def obter_total_segundos(self):
        segundos = 0
        for row in self.store:
            if row[0]:
                segundos += time_to_seconds(row[3][10:18])

        return segundos

    def executa_ffmpeg(self, titulo, params, arquivos, segundosTotal , sufixoArquivo, arquivoDestino, showCompletedMessage):

        # Salva o STDOUT para o caso do ffmpeg ser interrompido
        savedStdout = sys.stdout

        # Efetua o processamento dos arquivos
        dialogVideo = VideoProgressDialog(win, arquivos, self.edit_origem.get_text(), titulo, params, sufixoArquivo, arquivoDestino, segundosTotal)
        dialogVideo.run()

        # Força a interrupção da conversão caso o usuário pressione cancel
        dialogVideo.must_stop = True
        if dialogVideo.failed:
            dialogVideo.destroy()
            sys.stdout = savedStdout
            return show_message("Falha na conversão!", "Ocorreram falhas durante o processamento de pelo menos uma video, verifique o log para mais informações.")

        global processo_ffmpeg
        if processo_ffmpeg is not None:
            try:
                processo_ffmpeg.kill()
                debug("O processo do ffmpeg foi interrompido pelo usuário.")
            except OSError:
                debug("O processo do ffmpeg foi finalizado com sucesso.")

        dialogVideo.destroy()
        debug("Processamento dos vídeos finalizada")

        # Retorna o STDOUT original
        sys.stdout = savedStdout

        if showCompletedMessage:
            show_message("Concluído!", "Processamento dos vídeos concluída com sucesso!")
            self.do_load_file_list(None)

    def do_click_logs(self, widget):  # @UnusedVariable
        debug("Visualizando os logs")
        LogViewerDialog(win).show_and_get_info()

    def do_click_close(self, widget):  # @UnusedVariable
        on_close(None, None)

    def on_tree_double_clicked(self, widget, row, col):  # @UnusedVariable
        debug("Duplo click na lista de arquivos (" + str(row) + "," + str(col.get_sort_column_id()) + ")")
        select = self.treeview.get_selection()
        model, treeiter = select.get_selected()
        self.store.set_value(treeiter, 0, not model[treeiter][0])
        self.do_atualiza_contador_selecao()

    def create_icon_and_label_button(self, label, icon, actionButton):
        debug("Criando botão: " + label)
        button = Gtk.Button.new()
        bGrid = Gtk.Grid()
        bGrid.set_column_spacing(6)
        bGrid.attach(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR), 0, 0, 1, 1)
        bGrid.attach(Gtk.Label(label=label, halign=Gtk.Align.CENTER), 1, 0, 1, 1)
        bGrid.show_all()
        button.add(bGrid)

        if actionButton:
            self.buttons.append(button)

        return button


def seconds_to_time(secs):
    return time.strftime('%H:%M:%S', time.gmtime(secs))


def time_to_seconds(time):
    ftr = [3600, 60, 1]
    try:
        return sum([a * b for a, b in zip(ftr, map(int, time.split(':')))])
    except ValueError:
        return 0


def get_caminho_ffmpeg():
    app = get_app_settings("caminho_ffmpeg")
    return app if app is not None else "ffmpeg"


def compare(model, row1, row2, user_data):  # @UnusedVariable
    sort_column, _ = model.get_sort_column_id()
    value1 = model.get_value(row1, sort_column)
    value2 = model.get_value(row2, sort_column)

    if value1 < value2:
        return -1
    elif value1 == value2:
        return 0
    else:
        return 1


def show_message(titulo, msg):
    debug("Exibindo dialog: " + titulo + " - " + msg)
    # Exibe um Dialog de aviso
    global win
    dialog = Gtk.MessageDialog(win, 0, Gtk.MessageType.INFO, Gtk.ButtonsType.CLOSE, titulo)
    dialog.format_secondary_text(msg)
    dialog.run()
    dialog.destroy()
    return None


def indent_xml(elem, level=0):
    i = "\n" + level * "\t"
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "\t"
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent_xml(elem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def set_app_settings(xmlTag, value):
    debug("Salvando configuração da aplicação: " + xmlTag + " = " + value)
    if not os.path.isfile(ARQUIVO_XML_SETTINGS):
        indent_and_save_xml(ET.Element('config'), ARQUIVO_XML_SETTINGS)

    config_tree = ET.parse(ARQUIVO_XML_SETTINGS, ET.XMLParser(remove_comments=False, strip_cdata=False))
    root = config_tree.getroot()

    # Remove o nó se já existir
    if config_tree.find("./" + xmlTag) is not None:
        root.remove(config_tree.find("./" + xmlTag))

    # Se o valor não for nulo, adicionar o novo nó
    if value is not None and value.strip():
        ET.SubElement(root, xmlTag).text = value

    indent_and_save_xml(config_tree.getroot(), ARQUIVO_XML_SETTINGS)


def get_app_settings(xmlTag):
    node_caminho = ET.parse(ARQUIVO_XML_SETTINGS, ET.XMLParser(remove_comments=False, strip_cdata=False)).find("./" + xmlTag)
    return None if node_caminho is None else node_caminho.text


def indent_and_save_xml(root_node, arquivo_xml):
    debug("Salvando o arquivo XML: " + arquivo_xml)
    indent_xml(root_node)
    pretty_xml = ET.tostring(root_node, encoding="UTF-8", method="xml", xml_declaration=True)
    arquivo = open(arquivo_xml, "wb")
    arquivo.write(pretty_xml)
    arquivo.close()


def debug(msg=''):
    try:
        linha = str(msg).strip()
    except (UnicodeEncodeError):
        linha = msg.encode("utf-8").strip()

    logger.debug(linha)


def human_size(nbytes):
    human = nbytes
    rank = 0
    if nbytes != 0:
        rank = int((math.log10(nbytes)) / 3)
        rank = min(rank, len(UNIDADES) - 1)
        human = nbytes / (1024.0 ** rank)
    f = ('%.2f' % human).rstrip('0').rstrip('.')
    return '%s %s' % (f, UNIDADES[rank])

# Fecha a aplicação, liberando o FileHandler do log


def on_close(self, widget):  # @UnusedVariable
    logHandler.close()
    logger.removeHandler(logHandler)
    sys.exit()


def get_codec_info(codec):
    # Recupera os parâmtros do ffmpeg para conversão
    resp = None
    if VIDEO_H265 == codec:
        resp = {"params":["-c:v", "libx265", "-acodec", "aac", "-strict", "-2"], "sufixo":"_H265.mp4"}        
    elif VIDEO_H264 == codec:
        resp = {"params":["-c:v", "libx264", "-acodec", "aac", "-strict", "-2"], "sufixo":"_H264.mp4"}        
    elif VIDEO_VP8 == codec:            
        resp = {"params":["-c:v", "libvpx", "-b:v", "1M", "-c:a", "libvorbis"], "sufixo":"_VP8.webm"}        
    elif VIDEO_VP9 == codec:
        resp = {"params":["-c:v", "libvpx-vp9", "-b:v", "2M", "-c:a", "libopus"], "sufixo":"_VP9.webm"}        
    elif AUDIO_MP3 == codec:
        resp = {"params":["-vn", "-f", "mp3", "-ab", "192000"], "sufixo":"_MP3.mp3"}        
    elif AUDIO_FLAC == codec:
        resp = {"params":[ "-vn", "-acodec", "flac"], "sufixo":"_FLAC.flac"}        
    elif AUDIO_AAC == codec:
        resp = {"params":[ "-vn", "-acodec", "aac", "-strict", "-2"], "sufixo":"AAC.m4a"}        
    elif AUDIO_OGG == codec:
        resp = {"params":["-vn", "-acodec", "libvorbis"], "sufixo":"_Vorbis.ogg"}        
    return resp


def get_ffmpeg_features():
    global ffmpeg_features

    if ffmpeg_features is None:
        processo_ffmpeg = subprocess.Popen([get_caminho_ffmpeg()], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)

        linhas = ""
        for line in iter(processo_ffmpeg.stdout.readline, ''):
            if "--" in line:
                linhas = linhas + line            
                    
        processo_ffmpeg.stdout.close()
        processo_ffmpeg.wait()

        ffmpeg_features = []
        pattern = re.compile("--enable-[^\s]+|disable-[^\s]+")
        for m in pattern.finditer(linhas):
            ffmpeg_features.append(m.group())        
    
    return ffmpeg_features


ffmpeg_features = None


# Constantes da aplicação
UNIDADES = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
DIR_APPLICATION = os.path.dirname(os.path.realpath(__file__))
ARQUIVO_XML_SETTINGS = DIR_APPLICATION + os.sep + "settings.xml"
ARQUIVO_LOG = DIR_APPLICATION + os.sep + "application.log"
ARQUIVO_VIDEOS_CONCATENA = DIR_APPLICATION + os.sep + "videos_concatena.txt"

show_debug_msg = False  # True para exibir mensagens de debug
versao_aplicacao = "v1.0"
arquivos_origem = None
processo_ffmpeg = None

# its win32, maybe there is win64 too?
is_windows = sys.platform.startswith('win')

# Remove o arquivo de log anterior e cria o logger
if os.path.isfile(ARQUIVO_LOG):
    os.remove(ARQUIVO_LOG)

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(level=logging.DEBUG, format=FORMAT)
logger = logging.getLogger('-')

logHandler = logging.FileHandler(ARQUIVO_LOG)
logger.addHandler(logHandler)

# Lê os parâmetros da aplicação
try:
    opts, args = getopt.getopt(sys.argv[1:], "hd", [])
except getopt.GetoptError:
    print('videotools.py -h (help) -d (debug)')
    sys.exit(2)
for opt, arg in opts:
    if opt == '-h':
        print("\nPrograma para edição de arquivos de vídeo")
        print("\nUso: videotools.py -h (help) -d (debug)")
        print("\nExemplo: ./videotools.py -d\"\n")
        sys.exit()

# Força UTF-8 por padrão
if sys.version_info < (3, 0):
    reload(sys)
    sys.setdefaultencoding("utf-8")

# Cria as configurações padrão da aplicação
if not os.path.isfile(ARQUIVO_XML_SETTINGS):
    set_app_settings("dir_origem", os.path.expanduser('~'))
    set_app_settings("extensoes_video", "wmv|avi|mpg|3gp|mov|m4v|mts|mp4|webm")
    set_app_settings("caminho_ffmpeg", "ffmpeg")

if not spawn.find_executable(get_caminho_ffmpeg()):
    print("Não foi possível encontrar o aplicativo necessário ffmpeg.")
    print("Verifique a configuração do caminho do ffmpeg no arquivo settings.xml")
    print("A configuração atual é: "+ get_caminho_ffmpeg())
    sys.exit(2)    
    

# Codecs de Video
VIDEO_H265 = "Video H265"
VIDEO_H264 = "Video H264"
VIDEO_VP8 = "Video VP8"
VIDEO_VP9 = "Video VP9"
CODECS_VIDEO = []

if "--enable-libx264" in get_ffmpeg_features():
    CODECS_VIDEO.append(VIDEO_H264)
    
if "--enable-libx265" in get_ffmpeg_features():
    CODECS_VIDEO.append(VIDEO_H265)

if "--enable-libvpx" in get_ffmpeg_features():
    CODECS_VIDEO.append(VIDEO_VP8)
    CODECS_VIDEO.append(VIDEO_VP9)

# Codecs de Audio
AUDIO_MP3 = "Extrair audio - MP3"
AUDIO_AAC = "Extrair audio - AAC"
AUDIO_FLAC = "Extrair audio - FLAC"
AUDIO_OGG = "Extrair audio - Ogg Vorbis"
CODECS_AUDIO = [AUDIO_AAC, AUDIO_FLAC] 

if "--enable-libmp3lame" in get_ffmpeg_features():
    CODECS_AUDIO.append(AUDIO_MP3)

if "--enable-libvorbis" in get_ffmpeg_features():
    CODECS_AUDIO.append(AUDIO_OGG)

# Calling GObject.threads_init() is not needed for PyGObject 3.10.2+
GObject.threads_init()

# Monta a UI
win = MainWindow()
win.connect('delete-event', on_close)
win.show_all()
Gtk.main()
