import { MainLayout } from './components/layout';
import { QuantizationPage, DevicesPage, DeploymentPage, ComparisonPage, HomePage } from './pages';
import { useAppStore } from './store/appStore';

function App() {
  const { currentPage } = useAppStore();

  const renderPage = () => {
    switch (currentPage) {
      case 'home':
        return <HomePage />;
      case 'quantization':
        return <QuantizationPage />;
      case 'devices':
        return <DevicesPage />;
      case 'deployment':
        return <DeploymentPage />;
      case 'comparison':
        return <ComparisonPage />;
      default:
        return <HomePage />;
    }
  };

  return (
    <MainLayout>
      {renderPage()}
    </MainLayout>
  );
}

export default App;
