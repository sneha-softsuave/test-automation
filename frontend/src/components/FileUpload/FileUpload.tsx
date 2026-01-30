import { useState, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload,
  FileSpreadsheet,
  FileJson,
  X,
  CheckCircle,
  AlertCircle,
  Loader2,
  Sparkles,
  Rocket,
} from 'lucide-react';
import { useStore } from '../../store/useStore';
import { uploadAndParse } from '../../services/api';
import styles from './FileUpload.module.css';

export const FileUpload = () => {
  const {
    setTestSuite,
    setRawTestCases,
    setCurrentView,
    uploadProgress,
    setUploadProgress,
    isUploading,
    setIsUploading,
    addNotification,
  } = useStore();

  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [projectName, setProjectName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    setError(null);

    const file = e.dataTransfer.files[0];
    if (file) {
      validateAndSetFile(file);
    }
  }, []);

  const validateAndSetFile = (file: File) => {
    const validTypes = [
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'application/vnd.ms-excel',
      'application/json',
      '.xlsx',
      '.xls',
      '.json',
    ];

    const isValidType =
      validTypes.some((type) => file.type === type) ||
      file.name.endsWith('.xlsx') ||
      file.name.endsWith('.xls') ||
      file.name.endsWith('.json');

    if (!isValidType) {
      setError('Please upload an Excel (.xlsx, .xls) or JSON file');
      return;
    }

    setSelectedFile(file);
    setError(null);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      validateAndSetFile(file);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) return;

    setIsUploading(true);
    setUploadProgress(0);
    setError(null);

    try {
      const result = await uploadAndParse(
        selectedFile,
        projectName || 'Test Automation Project',
        baseUrl || undefined,
        (progress) => setUploadProgress(progress)
      );

      // Store both parsed suite and raw data (raw data needed for Deep Agent)
      setTestSuite(result.testSuite);
      setRawTestCases(result.rawData);

      addNotification('success', `Successfully loaded ${result.testSuite.test_cases.length} test cases`);
      setCurrentView('suite');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to upload and parse file';
      setError(message);
      addNotification('error', message);
    } finally {
      setIsUploading(false);
      setUploadProgress(0);
    }
  };

  const clearFile = () => {
    setSelectedFile(null);
    setError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const getFileIcon = () => {
    if (!selectedFile) return Upload;
    if (selectedFile.name.endsWith('.json')) return FileJson;
    return FileSpreadsheet;
  };

  const FileIcon = getFileIcon();

  return (
    <div className={styles.container}>
      {/* Header */}
      <motion.div
        className={styles.header}
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <div className={styles.headerIcon}>
          <Sparkles size={32} />
        </div>
        <h1 className={styles.title}>
          Upload Test Cases
        </h1>
        <p className={styles.subtitle}>
          Import your Excel or JSON test cases to get started with automated testing
        </p>
      </motion.div>

      {/* Upload Zone */}
      <motion.div
        className={styles.uploadSection}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.1 }}
      >
        <motion.div
          className={`${styles.dropzone} ${isDragging ? styles.dragging : ''} ${selectedFile ? styles.hasFile : ''} ${error ? styles.hasError : ''}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => !selectedFile && fileInputRef.current?.click()}
          whileHover={!selectedFile ? { scale: 1.01 } : {}}
          whileTap={!selectedFile ? { scale: 0.99 } : {}}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls,.json"
            onChange={handleFileSelect}
            className={styles.fileInput}
          />

          <AnimatePresence mode="wait">
            {selectedFile ? (
              <motion.div
                key="file-selected"
                className={styles.selectedFile}
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
              >
                <div className={styles.fileIconLarge}>
                  <FileIcon size={48} />
                </div>
                <div className={styles.fileInfo}>
                  <span className={styles.fileName}>{selectedFile.name}</span>
                  <span className={styles.fileSize}>
                    {(selectedFile.size / 1024).toFixed(1)} KB
                  </span>
                </div>
                <motion.button
                  className={styles.clearButton}
                  onClick={(e) => {
                    e.stopPropagation();
                    clearFile();
                  }}
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.9 }}
                >
                  <X size={20} />
                </motion.button>
              </motion.div>
            ) : (
              <motion.div
                key="drop-prompt"
                className={styles.dropPrompt}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                <div className={styles.uploadIconWrapper}>
                  <div className={styles.uploadIconBg} />
                  <Upload size={40} className={styles.uploadIcon} />
                </div>
                <h3 className={styles.dropTitle}>
                  Drop your file here
                </h3>
                <p className={styles.dropText}>
                  or click to browse
                </p>
                <div className={styles.supportedFormats}>
                  <span className={styles.formatBadge}>
                    <FileSpreadsheet size={14} /> Excel
                  </span>
                  <span className={styles.formatBadge}>
                    <FileJson size={14} /> JSON
                  </span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Upload Progress */}
          <AnimatePresence>
            {isUploading && (
              <motion.div
                className={styles.progressOverlay}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                <div className={styles.progressContent}>
                  <Loader2 size={32} className={styles.spinner} />
                  <span className={styles.progressText}>
                    {uploadProgress < 100 ? `Uploading... ${uploadProgress}%` : 'Parsing test cases...'}
                  </span>
                  <div className={styles.progressBar}>
                    <motion.div
                      className={styles.progressFill}
                      initial={{ width: 0 }}
                      animate={{ width: `${uploadProgress}%` }}
                    />
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>

        {/* Error Message */}
        <AnimatePresence>
          {error && (
            <motion.div
              className={styles.error}
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
            >
              <AlertCircle size={16} />
              <span>{error}</span>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      {/* Configuration */}
      <motion.div
        className={styles.config}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.2 }}
      >
        <h3 className={styles.configTitle}>Configuration</h3>
        <div className={styles.configGrid}>
          <div className={styles.inputGroup}>
            <label className={styles.label}>Project Name</label>
            <input
              type="text"
              className={styles.input}
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="My Test Project"
            />
          </div>
          <div className={styles.inputGroup}>
            <label className={styles.label}>Base URL (optional)</label>
            <input
              type="url"
              className={styles.input}
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://example.com"
            />
          </div>
        </div>
      </motion.div>

      {/* Action Button */}
      <motion.div
        className={styles.actions}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.3 }}
      >
        <motion.button
          className={styles.uploadButton}
          onClick={handleUpload}
          disabled={!selectedFile || isUploading}
          whileHover={selectedFile && !isUploading ? { scale: 1.02, y: -2 } : {}}
          whileTap={selectedFile && !isUploading ? { scale: 0.98 } : {}}
        >
          {isUploading ? (
            <>
              <Loader2 size={20} className={styles.spinner} />
              Processing...
            </>
          ) : (
            <>
              <Rocket size={20} />
              Parse & Load Test Cases
            </>
          )}
        </motion.button>
      </motion.div>

      {/* Features */}
      <motion.div
        className={styles.features}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.4 }}
      >
        <div className={styles.feature}>
          <CheckCircle size={16} className={styles.featureIcon} />
          <span>AI-powered test case parsing</span>
        </div>
        <div className={styles.feature}>
          <CheckCircle size={16} className={styles.featureIcon} />
          <span>Automatic selector generation</span>
        </div>
        <div className={styles.feature}>
          <CheckCircle size={16} className={styles.featureIcon} />
          <span>Playwright script generation</span>
        </div>
      </motion.div>
    </div>
  );
};
