import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Box,
  Button,
  Center,
  Collapse,
  Grid,
  Group,
  Loader,
  NumberInput,
  Pagination,
  Paper,
  ScrollArea,
  Stack,
  Switch,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";

const isClient = typeof window !== "undefined";

const getStored = (key, fallback = "") => {
  if (!isClient) return fallback;
  const value = window.localStorage.getItem(key);
  return value ?? fallback;
};

const setStored = (key, value) => {
  if (!isClient) return;
  if (value === undefined || value === null || value === "") {
    window.localStorage.removeItem(key);
    return;
  }
  window.localStorage.setItem(key, String(value));
};

const toFileUrl = (filePath, pathToFileURL) => {
  if (!filePath) return "";
  if (typeof pathToFileURL === "function") {
    try {
      return pathToFileURL(filePath).href;
    } catch (_) {
      // ignore and fall back
    }
  }
  let normalized = filePath.replaceAll("\\", "/");
  if (!normalized.startsWith("/")) {
    normalized = `/${normalized}`;
  }
  return encodeURI(`file://${normalized}`);
};

const normalizeChunk = (chunk) => {
  if (!chunk) return "";
  return chunk.replace(/\r\n?/g, "\n");
};

function useElectron() {
  return useMemo(() => {
    if (!isClient) return null;
    const globalElectron = window.electron ?? window.require?.("electron");
    return globalElectron ?? null;
  }, []);
}

function useNodeModules() {
  return useMemo(() => {
    if (!isClient || !window.require) return {};
    try {
      const fs = window.require("fs");
      const path = window.require("path");
      const { pathToFileURL } = window.require("url");
      return { fs, path, pathToFileURL };
    } catch (error) {
      console.error("Unable to access Node modules from renderer:", error);
      return {};
    }
  }, []);
}

function App() {
  const electron = useElectron();
  const ipcRenderer = electron?.ipcRenderer;
  const { fs, path, pathToFileURL } = useNodeModules();

  const preloadToken = useRef(0);
  const scrollViewportRef = useRef(null);

  const legacyCellStack = useMemo(
    () => (isClient ? window.localStorage.getItem("cellStack") : null),
    [],
  );

  const [templatePath, setTemplatePath] = useState(() =>
    getStored("templatePath"),
  );
  const [albumPath, setAlbumPath] = useState(() => getStored("albumPath"));
  const [customOutputDir, setCustomOutputDir] = useState(() =>
    getStored("outputDir"),
  );
  const [parity, setParity] = useState(() => {
    const storedParity = getStored("parity") || legacyCellStack;
    const parsed = Number.parseInt(storedParity || "1", 10);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : 1;
  });
  const [copies, setCopies] = useState(() => {
    const stored = getStored("copies", "1");
    const parsed = Number.parseInt(stored || "1", 10);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : 1;
  });
  const [cellStackMode, setCellStackMode] = useState(() => {
    const stored = getStored("cellStackMode");
    if (stored === "true" || stored === "false") {
      return stored === "true";
    }
    if (
      legacyCellStack &&
      Number.isInteger(Number.parseInt(legacyCellStack, 10)) &&
      Number.parseInt(legacyCellStack, 10) > 1
    ) {
      return true;
    }
    return false;
  });
  const [testDataEnabled, setTestDataEnabled] = useState(
    () => getStored("testDataEnabled") === "true",
  );
  const [testDataValue, setTestDataValue] = useState(() =>
    getStored("testDataValue"),
  );

  const [isGenerating, setIsGenerating] = useState(false);
  const [progressLog, setProgressLog] = useState("");
  const [outputDir, setOutputDir] = useState("");
  const [outputStatus, setOutputStatus] = useState("No pages loaded");
  const [outputPages, setOutputPages] = useState([]);
  const [currentPage, setCurrentPage] = useState(0);
  const [isLoadingOutput, setIsLoadingOutput] = useState(false);
  const [activeTab, setActiveTab] = useState("template");

  useEffect(() => {
    setStored("templatePath", templatePath);
  }, [templatePath]);

  useEffect(() => {
    setStored("albumPath", albumPath);
  }, [albumPath]);

  useEffect(() => {
    setStored("outputDir", customOutputDir);
  }, [customOutputDir]);

  useEffect(() => {
    setStored("parity", parity);
  }, [parity]);

  useEffect(() => {
    setStored("copies", copies);
  }, [copies]);

  useEffect(() => {
    setStored("cellStackMode", cellStackMode ? "true" : "false");
  }, [cellStackMode]);

  useEffect(() => {
    setStored("testDataEnabled", testDataEnabled ? "true" : "false");
  }, [testDataEnabled]);

  useEffect(() => {
    const raw = testDataValue ?? "";
    if (!raw.trim()) {
      setStored("testDataValue", "");
      return;
    }
    setStored("testDataValue", raw);
  }, [testDataValue]);

  useEffect(() => {
    if (!legacyCellStack) return;
    if (!isClient) return;
    window.localStorage.removeItem("cellStack");
  }, [legacyCellStack]);

  const templatePreviewUrl = useMemo(
    () => toFileUrl(templatePath, pathToFileURL),
    [templatePath, pathToFileURL],
  );
  const currentOutputPage = outputPages[currentPage];
  const outputPreviewUrl = currentOutputPage ? currentOutputPage.url : "";
  const totalPages = outputPages.length;
  const paginationTotal = Math.max(totalPages, 1);
  const paginationValue = Math.min(currentPage + 1, paginationTotal);
  const testDataPreview = (testDataValue ?? "").trim();

  const buildSvgPathList = useCallback(
    (baseDir, metadata) => {
      if (!baseDir || !fs || !path) return [];
      if (
        Array.isArray(metadata?.pages_detail) &&
        metadata.pages_detail.length
      ) {
        return metadata.pages_detail.map((entry) => entry?.svg).filter(Boolean);
      }
      const svgDir = metadata?.svg_dir
        ? metadata.svg_dir
        : path.join(baseDir, "svg");
      const pageCount =
        typeof metadata?.page_count === "number" ? metadata.page_count : 0;
      if (pageCount > 0) {
        return Array.from({ length: pageCount }, (_, idx) =>
          path.join(svgDir, `page_${String(idx + 1).padStart(3, "0")}.svg`),
        );
      }
      try {
        const entries = fs.readdirSync(svgDir, { withFileTypes: true });
        return entries
          .filter(
            (entry) =>
              entry.isFile() && entry.name.toLowerCase().endsWith(".svg"),
          )
          .sort((a, b) =>
            a.name.localeCompare(b.name, undefined, { numeric: true }),
          )
          .map((entry) => path.join(svgDir, entry.name));
      } catch (_) {
        return [];
      }
    },
    [fs, path],
  );

  const prepareOutputPreview = useCallback(
    async (baseDir, metadata) => {
      preloadToken.current += 1;
      const token = preloadToken.current;

      if (!baseDir) {
        setOutputPages([]);
        setOutputStatus("No pages loaded");
        return;
      }

      const svgPaths = buildSvgPathList(baseDir, metadata);
      if (!svgPaths.length) {
        setOutputPages([]);
        setOutputStatus("No pages produced");
        return;
      }

      setIsLoadingOutput(true);
      setOutputStatus(
        `Loading ${svgPaths.length} page${svgPaths.length === 1 ? "" : "s"}…`,
      );

      try {
        const pages = await Promise.all(
          svgPaths.map((filePath, index) => {
            const url = toFileUrl(filePath, pathToFileURL);
            return new Promise((resolve, reject) => {
              const img = new Image();
              img.onload = () => resolve({ index, filePath, url });
              img.onerror = () =>
                reject(new Error(`Failed to load ${filePath}`));
              img.src = url;
            });
          }),
        );

        if (preloadToken.current !== token) return;

        setOutputPages(pages);
        setCurrentPage(0);
        setOutputStatus(
          pages.length === 1 ? "Page 1 of 1" : `Page 1 of ${pages.length}`,
        );
      } catch (error) {
        if (preloadToken.current !== token) return;
        console.error("Failed to preload output pages", error);
        setOutputPages([]);
        setOutputStatus("Failed to load output preview");
        notifications.show({
          color: "red",
          title: "Preview error",
          message:
            "Unable to load output previews. Check the logs for details.",
        });
      } finally {
        if (preloadToken.current === token) {
          setIsLoadingOutput(false);
        }
      }
    },
    [buildSvgPathList, pathToFileURL],
  );

  const clearOutputPreview = useCallback((status = "No pages loaded") => {
    preloadToken.current += 1;
    setOutputPages([]);
    setCurrentPage(0);
    setOutputStatus(status);
    setIsLoadingOutput(false);
  }, []);

  useEffect(() => {
    if (!ipcRenderer) return undefined;

    const progressListener = (_event, data) => {
      const raw = typeof data === "string" ? data : (data?.toString?.() ?? "");
      const normalized = normalizeChunk(raw);
      setProgressLog((prev) => prev + normalized);
    };

    const completeListener = (_event, payload) => {
      const { code, output, metadata, error } = payload ?? {};
      setIsGenerating(false);
      if (code === 0) {
        setOutputDir(output || "");
        prepareOutputPreview(output, metadata);
        setActiveTab("output");
        notifications.show({
          color: "teal",
          title: "Generation complete",
          message: "Output is ready. Review the pages or save final.pdf.",
        });
      } else {
        setOutputDir("");
        clearOutputPreview("Generation failed");
        const message = error || "Generation failed. See the log for details.";
        notifications.show({
          color: "red",
          title: "Generation failed",
          message,
        });
      }
    };

    ipcRenderer.on("generation-progress", progressListener);
    ipcRenderer.on("generation-complete", completeListener);

    return () => {
      ipcRenderer.removeListener("generation-progress", progressListener);
      ipcRenderer.removeListener("generation-complete", completeListener);
    };
  }, [ipcRenderer, prepareOutputPreview, clearOutputPreview]);

  useEffect(() => {
    const viewport = scrollViewportRef.current;
    if (!viewport) return;
    viewport.scrollTo({ top: viewport.scrollHeight });
  }, [progressLog]);

  useEffect(() => {
    if (!outputPages.length) return;
    setOutputStatus(`Page ${currentPage + 1} of ${outputPages.length}`);
  }, [currentPage, outputPages]);

  const handleChooseTemplate = async () => {
    if (!ipcRenderer) return;
    const selected = await ipcRenderer.invoke("select-template");
    if (!selected) {
      setTemplatePath("");
      return;
    }
    setTemplatePath(selected);
  };

  const handleChooseAlbum = async () => {
    if (!ipcRenderer) return;
    const selected = await ipcRenderer.invoke("select-album");
    if (!selected) {
      setAlbumPath("");
      return;
    }
    setAlbumPath(selected);
  };

  const handleChooseOutput = async () => {
    if (!ipcRenderer) return;
    const selected = await ipcRenderer.invoke("select-output");
    if (!selected) return;
    setCustomOutputDir(selected);
  };

  const handleClearOutput = () => {
    setCustomOutputDir("");
  };

  const handleGenerate = () => {
    if (!ipcRenderer) return;
    if (!templatePath || !albumPath) {
      notifications.show({
        color: "red",
        title: "Missing inputs",
        message: "Select a template and albums folder before generating.",
      });
      return;
    }
    const parityValue = Math.max(1, Number.parseInt(parity, 10) || 1);
    const copiesValue = Math.max(1, Number.parseInt(copies, 10) || 1);
    setProgressLog("");
    clearOutputPreview("Preparing generation…");
    setIsGenerating(true);
    setOutputDir("");
    const testDataPayload = testDataEnabled ? testDataPreview : null;
    ipcRenderer.send("run-generation", {
      album: albumPath,
      template: templatePath,
      parity: parityValue,
      cellStackMode: Boolean(cellStackMode),
      copies: copiesValue,
      outputDir: customOutputDir || null,
      testData: testDataPayload,
    });
  };

  const handleSaveFinal = async () => {
    if (!ipcRenderer || !outputDir) return;
    const success = await ipcRenderer.invoke("save-final", outputDir);
    if (success) {
      notifications.show({
        color: "teal",
        title: "Saved",
        message: "final.pdf copied to selected location.",
      });
    }
  };

  const canSave = Boolean(outputDir && outputPages.length);

  const parityDisplay = Number.isInteger(parity) ? parity : 1;
  const copiesDisplay = Number.isInteger(copies) ? copies : 1;

  return (
    <Box p="lg" bg="var(--mantine-color-dark-8)" miw={320}>
      <Stack gap="lg">
        <Title order={2} fw={500}>
          Gutenbird Studio
        </Title>
        <Grid gutter="lg">
          <Grid.Col span={{ base: 12, md: 6 }}>
            <Paper
              radius="lg"
              p="lg"
              withBorder
              style={{ background: "var(--mantine-color-dark-7)" }}
            >
              <Tabs value={activeTab} onChange={setActiveTab} color="blue">
                <Tabs.List grow>
                  <Tabs.Tab value="template">Template Preview</Tabs.Tab>
                  <Tabs.Tab value="output">Output Preview</Tabs.Tab>
                </Tabs.List>
                <Tabs.Panel value="template" pt="md">
                  {templatePreviewUrl ? (
                    <ImagePreview
                      src={templatePreviewUrl}
                      alt="Template preview"
                    />
                  ) : (
                    <Placeholder message="No template selected" />
                  )}
                </Tabs.Panel>
                <Tabs.Panel value="output" pt="md">
                  <Stack gap="sm">
                    <Box
                      pos="relative"
                      style={{
                        borderRadius: 12,
                        overflow: "hidden",
                        background: "rgba(17, 19, 27, 0.72)",
                        minHeight: 320,
                      }}
                    >
                      {isLoadingOutput && <Overlay message={outputStatus} />}
                      {outputPreviewUrl ? (
                        <ImagePreview
                          src={outputPreviewUrl}
                          alt="Output preview"
                        />
                      ) : (
                        <Placeholder message="No pages loaded" />
                      )}
                    </Box>
                    {totalPages > 0 && (
                      <Center>
                        <Pagination
                          size="sm"
                          radius="md"
                          total={paginationTotal}
                          value={paginationValue}
                          onChange={(page) => setCurrentPage(page - 1)}
                        />
                      </Center>
                    )}
                    <Center>
                      <Text size="sm" c="dimmed">
                        {outputStatus}
                      </Text>
                    </Center>
                  </Stack>
                </Tabs.Panel>
              </Tabs>
            </Paper>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6 }}>
            <Paper
              radius="lg"
              p="lg"
              withBorder
              style={{ background: "var(--mantine-color-dark-7)" }}
            >
              <Stack gap="lg">
                <FieldGroup label="Template">
                  <Group gap="sm" align="center" wrap="nowrap">
                    <Button onClick={handleChooseTemplate} size="sm">
                      Browse
                    </Button>
                    <Text
                      size="sm"
                      truncate
                      c={templatePath ? undefined : "dimmed"}
                      style={{ flex: 1 }}
                    >
                      {templatePath || "No template selected"}
                    </Text>
                  </Group>
                </FieldGroup>
                <FieldGroup label="Albums Root">
                  <Group gap="sm" align="center" wrap="nowrap">
                    <Button onClick={handleChooseAlbum} size="sm">
                      Browse
                    </Button>
                    <Text
                      size="sm"
                      truncate
                      c={albumPath ? undefined : "dimmed"}
                      style={{ flex: 1 }}
                    >
                      {albumPath || "No folder selected"}
                    </Text>
                  </Group>
                </FieldGroup>
                <FieldGroup label="Output Folder">
                  <Group gap="sm" align="center" wrap="nowrap">
                    <Button onClick={handleChooseOutput} size="sm">
                      Browse
                    </Button>
                    <Text
                      size="sm"
                      truncate
                      c={customOutputDir ? undefined : "dimmed"}
                      style={{ flex: 1 }}
                    >
                      {customOutputDir || "Using app data folder"}
                    </Text>
                    <Button
                      variant="light"
                      onClick={handleClearOutput}
                      size="sm"
                    >
                      Reset
                    </Button>
                  </Group>
                </FieldGroup>
                <FieldGroup label="Generation Options">
                  <Stack gap="sm">
                    <Switch
                      label="Cell stack mode"
                      checked={cellStackMode}
                      onChange={(event) =>
                        setCellStackMode(event.currentTarget.checked)
                      }
                    />
                    <Stack gap={4}>
                      <Switch
                        size="sm"
                        label="Test data"
                        checked={testDataEnabled}
                        onChange={(event) =>
                          setTestDataEnabled(event.currentTarget.checked)
                        }
                      />
                      <Collapse in={testDataEnabled}>
                        <TextInput
                          size="sm"
                          label="Flag value"
                          placeholder="Optional --testmode value"
                          value={testDataValue || ""}
                          onChange={(event) =>
                            setTestDataValue(event.currentTarget.value)
                          }
                        />
                        <Text size="xs" c="dimmed" mt={4}>
                          Flag preview:{" "}
                          <Text component="span" inherit fw={500}>
                            --testmode
                            {testDataPreview ? ` ${testDataPreview}` : ""}
                          </Text>
                        </Text>
                      </Collapse>
                    </Stack>
                    <Group gap="sm" wrap="wrap">
                      <NumberInput
                        label="Parity"
                        value={parityDisplay}
                        min={1}
                        step={1}
                        clampBehavior="strict"
                        hideControls={false}
                        onChange={(value) => {
                          const numeric = Number.parseInt(value, 10);
                          setParity(
                            Number.isFinite(numeric) && numeric > 0
                              ? numeric
                              : 1,
                          );
                        }}
                      />
                      <NumberInput
                        label="Copies"
                        value={copiesDisplay}
                        min={1}
                        step={1}
                        clampBehavior="strict"
                        hideControls={false}
                        onChange={(value) => {
                          const numeric = Number.parseInt(value, 10);
                          setCopies(
                            Number.isFinite(numeric) && numeric > 0
                              ? numeric
                              : 1,
                          );
                        }}
                      />
                    </Group>
                  </Stack>
                </FieldGroup>
                <Group grow>
                  <Button
                    onClick={handleGenerate}
                    disabled={isGenerating}
                    size="md"
                  >
                    {isGenerating ? "Generating…" : "Generate"}
                  </Button>
                  <Button
                    onClick={handleSaveFinal}
                    disabled={!canSave}
                    size="md"
                    variant="light"
                  >
                    Save final.pdf
                  </Button>
                </Group>
                <ScrollArea
                  h={220}
                  type="auto"
                  viewportRef={scrollViewportRef}
                  style={{
                    borderRadius: 12,
                    border: "1px solid rgba(255,255,255,0.1)",
                  }}
                >
                  <Box
                    p="sm"
                    style={{
                      fontFamily: "JetBrains Mono, Menlo, monospace",
                      fontSize: 13,
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {progressLog || (
                      <Text size="sm" c="dimmed">
                        Progress output will appear here.
                      </Text>
                    )}
                  </Box>
                </ScrollArea>
              </Stack>
            </Paper>
          </Grid.Col>
        </Grid>
      </Stack>
    </Box>
  );
}

const FieldGroup = ({ label, children }) => (
  <Stack gap={6}>
    <Text size="xs" fw={600} c="dimmed" tt="uppercase" lh={1.2}>
      {label}
    </Text>
    {children}
  </Stack>
);

const Placeholder = ({ message }) => (
  <Center
    style={{
      minHeight: 320,
      borderRadius: 12,
      background: "rgba(0, 0, 0, 0.24)",
    }}
  >
    <Text size="sm" c="dimmed">
      {message}
    </Text>
  </Center>
);

const ImagePreview = ({ src, alt }) => (
  <Box
    style={{
      width: "100%",
      minHeight: 320,
      display: "flex",
      justifyContent: "center",
      alignItems: "center",
      background: "white",
      borderRadius: 12,
      overflow: "hidden",
    }}
  >
    <img
      src={src}
      alt={alt}
      style={{ width: "100%", height: "100%", objectFit: "contain" }}
    />
  </Box>
);

const Overlay = ({ message }) => (
  <Box
    style={{
      position: "absolute",
      inset: 0,
      display: "flex",
      flexDirection: "column",
      gap: 12,
      alignItems: "center",
      justifyContent: "center",
      background: "rgba(20, 22, 28, 0.8)",
      backdropFilter: "blur(2px)",
    }}
  >
    <Loader />
    <Text size="sm" c="dimmed">
      {message}
    </Text>
  </Box>
);

export default App;
