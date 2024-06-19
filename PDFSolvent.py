#    __|  _ \ | \ \   /__|  \ |__ __|  _ \_ \ __|
#  \__ \ (   ||  \ \ / _|  .  |   |    __/|  |_|
#  ____/\___/____|\_/ ___|_|\_|  _|   _| ___/_|
#
#
#                                      Version 0.1
#
#  JP. Cardenuto <phillipe.cardenuto@ic.unicamp.br>
#                                        Jul, 2021
#
#  ===============================================
#
#  Copyright (C) [2021]
#
#  Permission is hereby granted, free of charge, to any person obtaining
#  a copy of this software and associated documentation files (the
#  "Software"), to deal in the Software without restriction, including
#  without limitation the rights to use, copy, modify, merge, publish,
#  distribute, sublicense, and/or sell copies of the Software, and to
#  permit persons to whom the Software is furnished to do so, subject to
#  the following conditions:
#
#  The above copyright notice and this permission notice shall be
#  included in all copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
#  EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
#  MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
#  IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
#  CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
#  TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
#  SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
#  ===============================================


# PYPDF4 and MUPDF has different license usage
# If you have interesst of using this software for comercial,
# make sure to respect their usage license.

# PyPDF4
# ------------------------------------------------------
import argparse
import os
import shutil
import tempfile
import tkinter as tk
import traceback
from collections import Counter
from tkinter import filedialog, messagebox
from typing import List, Tuple

# PyMuPDF
import fitz
from PyPDF4 import PdfFileReader, PdfFileWriter
from PyPDF4.generic import IndirectObject, NameObject, TextStringObject
from PyPDF4.pdf import ContentStream, PageObject
from PyPDF4.utils import PyPdfError, b_

entry_file = None


def select_file():
    file_path = filedialog.askopenfilename(
        filetypes=[("PDF files", "*.pdf"), ("All", "*.*")]
    )
    if file_path:
        entry_file.delete(0, tk.END)
        entry_file.insert(0, file_path)


def process(input_file) -> Tuple[bool, str]:
    # 在这里添加你的处理逻辑
    # 这是一个示例逻辑，你可以根据实际需求修改
    if input_file:
        return True, ""
    else:
        return False, "未选择文件"


def start_processing():
    file_path = entry_file.get()
    success, out_path, message = wrap_remove_watermarks(file_path)
    if success:
        output_file_path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("pdf files", "*.pdf"), ("All files", "*.*")],
        )
        if output_file_path:
            shutil.copy(out_path, output_file_path)
            messagebox.showinfo("成功", f"文件已保存到: {output_file_path}")
        else:
            messagebox.showwarning("取消", "文件保存已取消")
    else:
        messagebox.showerror("错误", message)


def cmd_main():
    parser = argparse.ArgumentParser(
        prog="PDFSolvent",
        description="Removes 'RETRACTED' watermarks from Academic PDF articles..",
        formatter_class=argparse.MetavarTypeHelpFormatter,
    )
    parser.add_argument(
        "--input_pdf",
        "-i",
        required=True,
        type=str,
        nargs="?",
        help="Path to the PDF input.",
    )
    parser.add_argument(
        "--output_pdf",
        "-o",
        type=str,
        nargs="?",
        required=True,
        help="Path to the output.",
    )
    parser.add_argument(
        "--mode",
        "-m",
        type=int,
        nargs="?",
        default=2,
        metavar=("mode"),
        help="""
        This program has three levels of aggressivity; as higher the level more damage it can cause to the final result.
        Even though, even for the maximum level of aggressivity, the images/photos embedded in the PDF are preserved.

        Aggressivity Level 1:
            All PDF stream resources that explicitly contain the information saying that it is a Watermark are removed.

        Aggressivity Level 2:
            All Watermarks from 1 and element Graphics that appear more than once along the PDF pages are removed.
            In addition, all 'RETRACTED' words are also removed.
            For some PDFs, this aggressivity level could remove the entire text from a Page.

        Aggressivity Level 3:
            All WM from 1 and 2 and all graphical elements are removed from the PDF.
            The only change for the Retraction Watermark not to be removed with such a level of aggressivity is the Retraction Watermark embedded as an Image File.
            In this case, we will preserve the Watermark since this function is designed not to erase any image/photo from the PDF.
    """,
    )

    args = vars(parser.parse_args())
    input_pdf = args["input_pdf"]
    output_pdf = args["output_pdf"]
    if type(args["mode"]) == list:
        mode = args["mode"][0]
    else:
        mode = args["mode"]
    remove_watermarks(input_pdf, output_pdf, mode)


# ----------------------------------------------------


def wrap_remove_watermarks(input_pdf, mode=2) -> Tuple[bool, str, str]:
    dir = tempfile.mkdtemp(prefix="pdf-watermark")
    output_pdf = os.path.join(dir, "output.pdf")
    try:
        remove_watermarks(input_pdf, output_pdf, mode)
        return True, output_pdf, ""
    except Exception:
        return False, output_pdf, traceback.format_exc()
        # return False, output_pdf, str(e)


def fix_recursive_IndirectObject(obj: object) -> object:
    """
    Resolve all IndirectObject attribution in a recursive fashion
    """
    if not isinstance(obj, IndirectObject):
        return obj

    obj = obj.getObject()

    for key, val in obj.items():
        obj[key] = fix_recursive_IndirectObject(val)
    return obj


def fig_covers_entiry_page(
    page: PageObject, source: PdfFileReader, operand: str, p_covered: int = 0.95
) -> bool:
    """
    Check if a figure cover more than 0.95 of a page
    if so, the image will be considerated as watermark

    Args:
        page: PyPDF page object
        source: PyPDF  file reader
        operand: PDF Stream Operand name addressing the figure
        p_covered: percentage of accepted coverage of the figure over the page
    """

    page_height = int(page.mediaBox.getHeight())
    page_width = int(page.mediaBox.getWidth())

    wm_operation_blocks, content = find_watermark_stack_block(
        page, source, [operand], aggressive=1
    )
    fig_width = 0
    fig_height = 0
    for p in wm_operation_blocks:
        # Check the cm operator found in the watermark stack block
        # This is riscky since we are supposing that the stram PDF operations
        # are well organized and with only one 'cm' operand in the watermark rendering stack block
        # Fig_width and Fig_height are the scaling factor (in x and y) presented in the
        # current transformation matrix (CTM)
        if len(content.operations[p][0]) == 6:
            fig_width = content.operations[p][0][0]
            fig_height = content.operations[p][0][3]
            break

    # If the minimum percentage among the position of the figure is more than
    # 0.95, the image is a watermark
    if min((fig_height / page_height), (fig_width / page_width) > p_covered):
        return True
    return False


def get_page_resources_watermarks(page: PageObject, source: PdfFileReader) -> List:
    """
    Return all operands keys from a PDF page Resource that might be
    from a watermark, i.e. named resources /Fm0 and /X0
    """

    if page.get("/Resources") is None:
        return []
    if page["/Resources"].get("/XObject") is None:
        return []

    xobject = page["/Resources"]["/XObject"].getObject()

    wm_keys = []
    for key in xobject.keys():
        # Usally the softwares like Adobe insert the watermark as a
        # named resource name as Fm, na dwith a information claiming
        # that this resource is a watermark
        if "/fm" in key.lower():
            info = xobject[key].get("/PieceInfo")
            if info is None:
                continue
            info = fix_recursive_IndirectObject(info)
            # If watermark found, include it to watermark_keys
            if ("watermark" in str(info).lower()) or "background" in str(info).lower():
                wm_keys.append(key)

        # Some Academic mistakely add the watermark to the PDF
        # As a form, without adding the informatio of watermark
        elif "/x" in key.lower():
            info = xobject[key].get("/Subtype")
            info = fix_recursive_IndirectObject(info)
            if "form" in str(info).lower():
                wm_keys.append(key)
            if fig_covers_entiry_page(page, source, key):
                wm_keys.append(key)

    return wm_keys


def get_GS_watermark_from_pdf(source: PdfFileReader) -> List:
    """
    This function tends to admit a watermark more aggresived by
    looking at the graphic /GS from the ExtGState

    So, it scans all pages from PDF File Source
    checking the number of GS operation frequency
    in more than one page. Each GS that
    occurs in more than one page, we assume that it is a
    watermark. It works, but can cause some false-positive.
    """
    # Initialize extGstates
    extGstates = []

    # Check Gs along the pdf document
    for page in range(source.getNumPages()):
        page = source.getPage(page)
        if not page.get("/Resources"):
            continue
        if not page["/Resources"].get("/ExtGState"):
            continue
        extGstates += list(page["/Resources"]["/ExtGState"].keys())

    # Count the occurrence of each Gs along the source pdf
    watermarks = []
    for key, occ in Counter(extGstates).items():
        if occ > 1:
            watermarks.append(key)

    return watermarks


def get_operands_watermarks_list(source: PdfFileReader, aggressive: int):
    """
    According to the user aggresive will, returns the stream operands names
    that might be considerated as watermarks.

    Args:
        source: PyPDF  file reader
        aggressive: Integer in [1,3]
    """

    # Check the GS operators
    # Our heuristic is that if the GS appears in more then
    # one page, then it should be considerated as a watermark
    watermarks = get_GS_watermark_from_pdf(source) if aggressive > 1 else []
    for page in range(source.getNumPages()):
        page = source.getPage(page)
        watermarks += get_page_resources_watermarks(page, source)

    watermarks = list(set(watermarks))
    return watermarks


def check_blockqQ_has_watermark(block: ContentStream, watermarks: List) -> bool:
    """
    Check if the rendering watermark instruction
    is present in the Stream block.
    We are assuming that the blocks are within 'q' 'Q' structure instruction stack
    """

    for operands, _ in block:
        # operands is a list of operand
        for op in operands:
            if not isinstance(op, str):
                continue
            if op in watermarks:
                return True

    return False


def find_watermark_stack_block(
    page: PageObject, source: PdfFileReader, watermarks: List, aggressive: int
) -> Tuple[List, ContentStream]:
    """
    Find the all blocks of instructions stacks within the 'q' 'Q'
    that the Watermark instruction is involved

    Args:
        page: PyPDF page object
        source: PyPDF  file reader
        watermarks: List of watermark operand names inside the PDF
        aggressive: Integer in [1,3]
    """

    # Check if page has contents
    if page.get("/Contents") is None:
        return [], None

    # q Q stack blocks with watermarks
    wm_blocksqQ = []

    Found = False
    index_op = 0
    # Get content objects id
    content_object = page["/Contents"].getObject()
    # Retrive contents stream
    content = ContentStream(content_object, source)

    # For each operand check if it a q, if yes start a new
    # block, inserting the indeces and the operations involved
    # in lists.
    # If for any reason an operand of a Image (Im) or a text (BT)
    # is found, we will ignore that block, even if it contains a watermark;
    # otherwise we would erase valid information from the PDF.

    # If the Aggressive is more than 2, we don't check if the stack of intructions operands
    # have a watermark's operand or not, we include everthing that either isn't a text
    # nor a image as a watermark block of instruction.
    for operands, operator in content.operations:
        if Found:
            new_block_indeces.append(index_op)
            new_block_ops.append((operands, operator))

        if operator == b_("q"):
            Found = True
            new_block_indeces = [index_op]
            new_block_ops = [(operands, operator)]

        if type(operands) is list:
            if len(operands) > 0:
                if isinstance(operands[0], NameObject):
                    name = str(operands[0]).lower()
                    if "/im" in name:
                        Found = False
                        new_block_indeces = []
                        new_block_ops = []

        if operands == b_("BT"):
            Found = False
            new_block_indeces = []
            new_block_ops = []

        if operator == b_("Q") and Found:
            Found = False
            # If aggressive is more than 3, include even blocks that
            # don't have explicit a watermark operand to be erased
            if aggressive <= 2:
                if check_blockqQ_has_watermark(new_block_ops, watermarks):
                    wm_blocksqQ += new_block_indeces
            else:
                wm_blocksqQ += new_block_indeces

        index_op += 1

    return wm_blocksqQ, content


def remove_watermark_from_page(
    page: PageObject, source: PdfFileReader, watermarks: List, aggressive: int
) -> Tuple[PageObject, ContentStream]:
    """
    Considering the list 'watermark' of operand names consideraded as
    Watermark Resources, find all stack of rendering instruction that it participates
    and remove them from the page

    Args:
        page: PyPDF page object
        source: PyPDF  file reader
        watermarks: List of watermark operand names inside the PDF
        aggressive: Integer in [1,3]
    """

    wm_operation_blocks, content = find_watermark_stack_block(
        page, source, watermarks, aggressive
    )

    non_wm_blocks = []
    if not content is None:
        for ops_index, ops in enumerate(content.operations):
            if ops_index in wm_operation_blocks:
                continue
            non_wm_blocks.append((ops))

        # Update Page content with non watermark blocks
        content.operations = non_wm_blocks
        page.__setitem__(NameObject("/Contents"), content)

    if page.get("/Resources") is None:
        return page, content

    # Remove watermarks from the page resources
    for wm in watermarks:
        if page["/Resources"].get("/XObject"):
            if wm in page["/Resources"]["/XObject"].keys():
                page["/Resources"]["/XObject"].pop(wm)

        if page["/Resources"].get("/ExtGState"):
            if wm in page["/Resources"]["/ExtGState"].keys():
                page["/Resources"]["/ExtGState"].pop(wm)

    return page, content


def remove_graphical_watermarks_from_contents(
    page: PageObject, source: PdfFileReader
) -> PageObject:
    """
    This is a more aggressive watermark removal function.
    It removes all graphical operator instruction from a page stream
    Args:
        page: PyPDF page object
        source: PyPDF  file reader
    Return:
        page
    """

    graph_operators = [
        "f",
        "F",
        "B",
        "B*",
        "b",
        "b*",
        "n",
        "W",
        "W*",
        "m",
        "l",
        "c",
        "v",
        "y",
        "h",
        "re",
    ]
    if page.get("/Contents") is None:
        return page

    # Get content objects id
    content_object = page["/Contents"].getObject()
    # Retrive contents stream
    content = ContentStream(content_object, source)

    # List of non graphical operations, remainded
    non_graphical_operations = []

    # Analyze each operation, keep only the non graphical ones
    for operands, operator in content.operations:
        if not operator in [b_(i) for i in graph_operators]:
            non_graphical_operations.append((operands, operator))

    # update content operations
    content.operations = non_graphical_operations
    page.__setitem__(NameObject("/Contents"), content)

    return page


def remove_retracted_watermarks_letters(
    page: PageObject, content: ContentStream
) -> PageObject:
    """
    This is a watermark removal function.
    It replaces the word "RETRACTED" from the page text
    by "".
    Args:
        page: PyPDF page object
        source: PyPDF  file reader
    Return:
        page
    """

    if content is None:
        return page

    # Check if the 'retracted' term appears in the text
    operations = []
    for operands, operator in content.operations:
        # TJ or Tj flags the occurence of a text term
        if operator == b_("TJ") or operator == b_("Tj"):
            text = operands

            if not text:
                operations.append((operands, operator))
                continue

            if isinstance(text[0], list):
                text = " ".join([str(i) for i in text])

            elif isinstance(text[0], str):
                text = text[0]

            else:
                operations.append((operands, operator))
                continue

            if ("retracted" in text.lower()) and len(text) < 30:
                operands = TextStringObject("")

        operations.append((operands, operator))

    content.operations = operations

    # update content operations
    page.__setitem__(NameObject("/Contents"), content)

    return page


def fitz_solvent_watermarks(input_pdf: str, output_pdf: str):
    """
    Use the PyMuPDF function to remove watermark

    In case PyPDF fails, we use the solution from PyMupdf
    REFERENCE: https://github.com/pymupdf/PyMuPDF/issues/468#issuecomment-601142235

    Args:
        input_pdf: str,
        output_pdf: str):

    """
    doc = fitz.open(input_pdf)

    for page in doc:
        page.cleanContents()  # cleanup page painting commands

        if len(page.getContents()) > 0:
            xref = page.getContents()[0]  # get xref of the resulting source
            cont0 = (
                doc.xrefStream(xref).decode().splitlines()
            )  # and read it as lines of strings
            cont1 = []  # will contain reduced cont lines
            found = False  # indicates we are inside watermark instructions

            for line in cont0:
                if line.startswith("/Artifact") and (
                    ("/Background" in line) or ("/Watermark" in line)
                ):  # start of watermark
                    found = True  # switch on
                    continue  # and skip line
                if found and line == "EMC":  # end of watermark
                    found = False  # switch off
                    continue  # and skip line
                if found is False:  # copy commands while outside watermarks
                    cont1.append(line)

            cont = "\n".join(cont1)  # new paint commands source
            doc.updateStream(
                xref, cont.encode()
            )  # replace old one with 'bytes' version

        # Removing annotationg, just in case
        annot = page.firstAnnot
        while annot:
            annot = page.deleteAnnot(annot)

    doc.save(output_pdf)  # original uses garbage=4


def remove_watermarks(inputFile: str, outputFile: str, aggressive: int = 2):
    """
    Removes 'RETRACTED' watermarks from Academic PDF articles.

    This function has three levels of aggressivity; as higher the level more damage it can cause to the final result.
    Even though, even for the maximum level of aggressivity, the images/photos embedded in the PDF are preserved.

    Aggressivity Level 1:
        All PDF stream resources that explicitly contain the information saying that it is a Watermark are removed.

    Aggressivity Level 2:
        All Watermarks from 1 and element Graphics that appear more than once along the PDF pages are removed.
        In addition, all 'RETRACTED' words are also removed.
        For some PDFs, this aggressivity level could remove the entire text from a Page.

    Aggressivity Level 3:
        All WM from 1 and 2 and all graphical elements are removed from the PDF.
        The only change for the Retraction Watermark not to be removed with such a level of aggressivity is the Retraction Watermark embedded as an Image File.
        In this case, we will preserve the Watermark since this function is designed not to erase any image/photo from the PDF.
    """

    try:
        with open(inputFile, "rb") as f:
            source = PdfFileReader(f, "rb")
            output = PdfFileWriter()

            watermarks = get_operands_watermarks_list(source, aggressive)
            watermarks = list(set(watermarks))

            # TODO
            # Process the followint FOR in parallel
            for page in range(source.getNumPages()):
                page = source.getPage(page)
                if aggressive > 0:
                    page, content = remove_watermark_from_page(
                        page, source, watermarks, aggressive
                    )
                if aggressive > 1:
                    page = remove_retracted_watermarks_letters(page, content)
                if aggressive > 2:
                    page = remove_graphical_watermarks_from_contents(page, source)
                output.addPage(page)

            with open(outputFile, "wb") as outputStream:
                output.write(outputStream)

    except PyPdfError:
        print("PyPDFError trying Pymupdf")
        fitz_solvent_watermarks(inputFile, outputFile)


if __name__ == "__main__":
    # 创建主窗口
    root = tk.Tk()
    root.title("PDF watermark-removal tool")

    # 文件选择框
    label_file = tk.Label(root, text="choose PDF file:")
    label_file.grid(row=0, column=0, padx=10, pady=5, sticky="e")

    entry_file = tk.Entry(root, width=40)
    entry_file.grid(row=0, column=1, padx=10, pady=5)

    button_file = tk.Button(root, text="browse", command=select_file)
    button_file.grid(row=0, column=2, padx=10, pady=5)

    # 开始按钮
    button_start = tk.Button(root, text="start", command=start_processing)
    button_start.grid(row=1, column=1, pady=20)

    # 运行主循环
    root.mainloop()
