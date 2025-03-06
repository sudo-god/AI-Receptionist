import { Component } from "@angular/core";
import { HttpClient, HttpErrorResponse, HttpHeaders } from "@angular/common/http";
import { NgxFileDropEntry, FileSystemFileEntry } from 'ngx-file-drop';
import { environment } from "../../../../environments/environment";
import { NbToastrService, NbComponentStatus } from '@nebular/theme';



const SESSION_ACCOUNT_KEY = 'sessionAccountId';

@Component({
  selector: 'file-upload',
  templateUrl: "./file-upload.component.html",
  styleUrls: ["./file-upload.component.css"]
})
export class FileUploadComponent {
  public allFiles: File[] = [];
  public newFilesToUpload: File[] = [];
  private allowedFileTypes = ['image/jpeg', 'image/jpg', 'image/png', 'application/pdf', 'text/plain', 'text/csv'];
  selectedAccountId: string | null = null;

  uploading = false; // Flag to indicate upload in progress
  uploadSuccess = false; // Flag for successful upload
  uploadError = '';    // Store any error messages

  constructor(private http: HttpClient, private toastrService: NbToastrService) { }

  ngOnInit() {
    this.selectedAccountId = sessionStorage.getItem(SESSION_ACCOUNT_KEY);
  }

  public dropped(files: NgxFileDropEntry[]) {
    for (const droppedFile of files) {
      if (droppedFile.fileEntry) {
        (droppedFile.fileEntry as FileSystemFileEntry).file((new_file: File) => {
          if (!this.allowedFileTypes.includes(new_file.type)) {
            // alert('File type not allowed: ' + new_file.name);
            this.showToast('danger', 'File type not allowed', 'Click to dismiss');
            return;
          }

          if (!this.allFiles.some(file => file.name === new_file.name)) {  
            this.allFiles.push(new_file);
            this.newFilesToUpload.push(new_file);
          } else {
            // alert('File already uploaded: ' + new_file.name);
            this.showToast('danger', 'File already uploaded', 'Click to dismiss');
            return;
          }
        });
      }
    }
    this.uploadFile();
  }

  public fileOver(event: Event){
    console.log(event);
  }

  public fileLeave(event: Event){
    console.log(event);
  }

  showToast(status: NbComponentStatus, title: string, message: string) {
    console.log("showing toast", status, message);
    this.toastrService.show(message, title, { status });
  }

  uploadFile() {
    for (const file of this.newFilesToUpload) {
      this.uploading = true;  // Set uploading to true
      this.uploadSuccess = false; // Reset success flag
      this.uploadError = ''; // Clear any previous errors
      console.log("uploading file", file);
      const formData = new FormData()
      formData.append('file', file, file.name)
      formData.append('account_id', this.selectedAccountId ?? '');

      // const headers = new HttpHeaders({
      //   'security-token': localStorage.getItem('auth_app_token') ?? '',
      //   'X-CSRFToken': this.getCookie('csrftoken')
      // })


      try {
        this.http.post<any>(`${environment.apiUrl}/upload-file/`, formData).subscribe(response => {
          console.log("RESPONSE");
          console.log(response);
          this.uploading = false;
          this.uploadSuccess = true;
          this.showToast('success', response.message, 'Click to dismiss');
        });
      } catch (error) {
        console.log("CAUGHT ERROR");
        console.log(error);
        this.uploading = false;
        this.uploadSuccess = false;
        this.uploadError = (error as HttpErrorResponse).statusText;
        console.log("upload error", this.uploadError);
        this.showToast('danger', this.uploadError, 'Click to dismiss');
      }
    }
    
    this.newFilesToUpload = [];
  }  
}
