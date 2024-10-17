import gradio as gr
import logging
import os
import tempfile
import time
import docx2txt
import openai

from adobe.pdfservices.operation.auth.service_principal_credentials import ServicePrincipalCredentials
from adobe.pdfservices.operation.exception.exceptions import ServiceApiException, ServiceUsageException, SdkException
from adobe.pdfservices.operation.io.cloud_asset import CloudAsset
from adobe.pdfservices.operation.io.stream_asset import StreamAsset
from adobe.pdfservices.operation.pdf_services import PDFServices
from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
from adobe.pdfservices.operation.pdfjobs.jobs.export_pdf_job import ExportPDFJob
from adobe.pdfservices.operation.pdfjobs.params.export_pdf.export_pdf_params import ExportPDFParams
from adobe.pdfservices.operation.pdfjobs.params.export_pdf.export_pdf_target_format import ExportPDFTargetFormat
from adobe.pdfservices.operation.pdfjobs.result.export_pdf_result import ExportPDFResult

# Initialize the logger
logging.basicConfig(level=logging.INFO)

# Set up OpenAI API key
openai.api_key = "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"

class ExportPDFToDOCX:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.credentials = ServicePrincipalCredentials(
            client_id="67a192fe77ad4e2f9771d8f6dcc10d4e",
            client_secret="p8e-oA61w9gc_B-L34L49Xu0to6E3MejqpA7"
        )
        self.pdf_services = PDFServices(credentials=self.credentials)

    def process(self, output_path):
        try:
            with open(self.pdf_path, 'rb') as file:
                input_stream = file.read()

            input_asset = self.pdf_services.upload(input_stream=input_stream, mime_type=PDFServicesMediaType.PDF)
            export_pdf_params = ExportPDFParams(target_format=ExportPDFTargetFormat.DOCX)
            export_pdf_job = ExportPDFJob(input_asset=input_asset, export_pdf_params=export_pdf_params)

            location = self.pdf_services.submit(export_pdf_job)
            pdf_services_response = self.pdf_services.get_job_result(location, ExportPDFResult)

            result_asset: CloudAsset = pdf_services_response.get_result().get_asset()
            stream_asset: StreamAsset = self.pdf_services.get_content(result_asset)

            with open(output_path, "wb") as file:
                file.write(stream_asset.get_input_stream())

            return output_path

        except ServiceApiException as e:
            if "CORRUPT_DOCUMENT" in str(e):
                logging.error(f"The input PDF file appears to be corrupted: {e}")
                return "CORRUPT_DOCUMENT"
            else:
                logging.exception(f'Service API Exception encountered while converting PDF: {e}')
                return None
        except (ServiceUsageException, SdkException) as e:
            logging.exception(f'Exception encountered while converting PDF: {e}')
            return None

def generate_few_shot_prompt(examples, task_description):
    prompt = f"{task_description}\n\nExamples:\n"
    for i, example in enumerate(examples, 1):
        prompt += f"Example {i}:\nInput: {example['input']}\nOutput: {example['output']}\n\n"
    prompt += "Now, please process the following text:\n"
    return prompt

def process_with_gpt4(text, prompt):
    try:
        max_tokens = 4000  # Maximum tokens allowed per request
        chunks = [text[i:i+max_tokens] for i in range(0, len(text), max_tokens)]
        
        processed_chunks = []
        
        for i, chunk in enumerate(chunks):
            chunk_prompt = f"{prompt}\n\nPart {i+1} of {len(chunks)}:\n{chunk}\n\nPlease improve this text by correcting any spelling or grammatical errors, enhancing clarity and coherence, and formatting it appropriately. Maintain the original meaning and key information."
            
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that processes and improves documents based on given examples and instructions."},
                    {"role": "user", "content": chunk_prompt}
                ],
                max_tokens=2000,  # Adjust as needed
                n=1,
                temperature=0.7,
            )
            
            processed_chunk = response.choices[0].message['content'].strip()
            processed_chunks.append(processed_chunk)
            
            # Sleep for a short time to avoid hitting rate limits
            time.sleep(20)  # Adjust this value based on your API rate limits
        
        return " ".join(processed_chunks)
    except Exception as e:
        logging.exception(f"Error in GPT-4 processing: {e}")
        return f"Error occurred during GPT-4 processing: {str(e)}"

def process_pdf(pdf_file, examples, task_description):
    try:
        # Create necessary directories
        os.makedirs('adobe_output', exist_ok=True)
        os.makedirs('final_output', exist_ok=True)

        # Save uploaded PDF
        pdf_path = os.path.join('adobe_output', 'input.pdf')
        with open(pdf_path, 'wb') as f:
            f.write(pdf_file if isinstance(pdf_file, bytes) else pdf_file.read())

        # Convert PDF to DOCX using Adobe
        exporter = ExportPDFToDOCX(pdf_path)
        docx_path = os.path.join('adobe_output', 'output.docx')
        docx_file = exporter.process(docx_path)

        if docx_file is None:
            return "Error occurred during PDF to DOCX conversion."
        elif docx_file == "CORRUPT_DOCUMENT":
            return "The uploaded PDF file appears to be corrupted. Please check the file and try again."

        # Extract text from DOCX
        text = docx2txt.process(docx_file)

        if not text.strip():
            return "The extracted text is empty. Please check the input PDF file."

        # Generate few-shot prompt
        prompt = generate_few_shot_prompt(examples, task_description)

        # Process with GPT-4
        final_text = process_with_gpt4(text, prompt)

        # Save final output
        final_output_path = os.path.join('final_output', 'processed_output.txt')
        with open(final_output_path, 'w', encoding='utf-8') as f:
            f.write(final_text)

        return final_text

    except Exception as e:
        logging.exception(f"Error processing PDF: {e}")
        return f"An error occurred while processing the PDF: {str(e)}"

def process_with_examples(pdf_file, example1_input, example1_output, example2_input, example2_output, task_description):
    examples = [
        {"input": example1_input, "output": example1_output},
        {"input": example2_input, "output": example2_output}
    ]
    return process_pdf(pdf_file, examples, task_description)

# Create Gradio interface
iface = gr.Interface(
    fn=process_with_examples,
    inputs=[
        gr.File(label="Upload PDF", type="binary"),
        gr.Textbox(label="Example 1 Input"),
        gr.Textbox(label="Example 1 Output"),
        gr.Textbox(label="Example 2 Input"),
        gr.Textbox(label="Example 2 Output"),
        gr.Textbox(label="Task Description", 
                   placeholder="e.g., 'Improve the formatting and clarity of the following document:'")
    ],
    outputs=gr.Textbox(label="Processed Text"),
    title="PDF Cleaner, Improver, and Formatter with GPT-4",
    description="Upload a PDF file and provide examples to guide the processing. The document will be converted, improved, and formatted using GPT-4 based on your inputs."
)

# Launch the app
iface.launch()